"""Ask OpenAI to find recurring issues and write the narrative.

Only masked ticket text is sent (see privacy.py). Exact counts come from
stats.py; the model is asked to interpret them, not to count.
"""

from __future__ import annotations

import json
from typing import Any

from .config import Settings
from .stats import Stats

CHUNK_SIZE = 150
DESC_CHARS = 300

SYSTEM = (
    "You are an experienced IT service management analyst. You read IT support tickets and "
    "find patterns that help an IT team reduce ticket volume. Be specific and practical. "
    "Only use information in the data you are given. Reply with JSON only."
)

THEMES_PROMPT = """Here are IT tickets from the last week, as JSON lines.
Group tickets that describe the same underlying problem (same app, same error, same device
model, same location, etc.). Only report groups with 2 or more tickets.

Return JSON: {{"themes": [{{"title": str, "description": str,
"ticket_numbers": [str], "likely_root_cause": str, "suggested_action": str}}]}}

Tickets:
{tickets}
"""

REPORT_PROMPT = """You are writing the weekly IT ticket analysis.

Exact statistics (trust these numbers, do not recount):
{stats}

Candidate recurring issues found in the tickets (may overlap, merge duplicates):
{themes}

Return JSON with these keys:
- "executive_summary": 3-5 sentences for IT management.
- "trend_insights": list of short bullet strings about volume and category changes vs last week.
- "recurring_issues": list of {{"title": str, "ticket_numbers": [str], "root_cause": str,
  "recommendation": str}}, most important first, max 10.
- "sla_insights": list of short bullet strings about SLA breaches and where they cluster.
- "hardware_insights": list of short bullet strings about hardware issues, mentioning
  barcodes of devices that appear repeatedly.
- "recommendations": list of 3-6 concrete next steps.
"""


def compact(t: dict[str, Any]) -> dict[str, Any]:
    out = {
        "number": t.get("number"),
        "type": t.get("sys_class_name") or t.get("table"),
        "category": t.get("category"),
        "subcategory": t.get("subcategory"),
        "priority": t.get("priority"),
        "state": t.get("state"),
        "group": t.get("assignment_group"),
        "short_description": t.get("short_description"),
        "description": (t.get("description") or "")[:DESC_CHARS],
    }
    if t.get("barcodes"):
        out["barcodes"] = t["barcodes"]
    return {k: v for k, v in out.items() if v}


def stats_summary(s: Stats) -> dict[str, Any]:
    return {
        "period": f"{s.period_start:%Y-%m-%d} to {s.period_end:%Y-%m-%d}",
        "total_tickets": s.total,
        "previous_period_total": s.previous_total,
        "by_type": dict(s.by_type),
        "top_categories_this_vs_last_week": [
            {"category": c, "this_week": a, "last_week": b} for c, a, b in s.by_category[:15]
        ],
        "tickets_per_day": dict(s.by_day),
        "by_priority": dict(s.by_priority),
        "top_assignment_groups": dict(s.by_group.most_common(10)),
        "open": s.open_count,
        "resolved": s.resolved_count,
        "avg_resolution_hours": round(s.avg_resolution_hours, 1) if s.avg_resolution_hours else None,
        "sla_breaches": len(s.sla_breaches),
        "sla_breaches_by_sla": dict(s.sla_by_name.most_common(10)),
        "sla_breaches_by_group": dict(s.sla_by_group.most_common(10)),
        "sla_breaches_by_priority": dict(s.sla_by_priority),
        "hardware_tickets": len(s.hardware),
        "barcodes_in_multiple_tickets": s.repeat_barcodes,
    }


class Analyzer:
    def __init__(self, settings: Settings):
        from openai import OpenAI  # imported here so --no-ai runs without the package

        kwargs: dict[str, Any] = {"api_key": settings.openai_api_key}
        if settings.openai_base_url:
            kwargs["base_url"] = settings.openai_base_url
        self.client = OpenAI(**kwargs)
        self.model = settings.openai_model

    def _ask(self, prompt: str) -> dict[str, Any]:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        return json.loads(resp.choices[0].message.content or "{}")

    def analyze(self, tickets: list[dict[str, Any]], stats: Stats) -> dict[str, Any]:
        themes: list[dict[str, Any]] = []
        for i in range(0, len(tickets), CHUNK_SIZE):
            chunk = tickets[i : i + CHUNK_SIZE]
            lines = "\n".join(json.dumps(compact(t), ensure_ascii=False) for t in chunk)
            themes.extend(self._ask(THEMES_PROMPT.format(tickets=lines)).get("themes", []))

        result = self._ask(
            REPORT_PROMPT.format(
                stats=json.dumps(stats_summary(stats), indent=1, default=str),
                themes=json.dumps(themes, ensure_ascii=False),
            )
        )
        return clean_result(result, {t["number"] for t in tickets})


def clean_result(result: dict[str, Any], valid_numbers: set[str]) -> dict[str, Any]:
    """Drop ticket numbers the model invented and make sure every key exists."""
    for key in ("trend_insights", "sla_insights", "hardware_insights", "recommendations"):
        result[key] = [str(x) for x in result.get(key) or []]
    result["executive_summary"] = str(result.get("executive_summary") or "")
    issues = []
    for item in result.get("recurring_issues") or []:
        nums = [n for n in item.get("ticket_numbers", []) if n in valid_numbers]
        if nums:
            item["ticket_numbers"] = nums
            issues.append(item)
    result["recurring_issues"] = issues
    return result
