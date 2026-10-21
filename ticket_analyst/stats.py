"""Plain number crunching. No AI here, so these figures are exact."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .servicenow import parse_dt

TYPE_LABELS = {
    "incident": "Incident",
    "sc_req_item": "Request item",
    "sc_request": "Request",
    "problem": "Problem",
    "change_request": "Change",
    "sc_task": "Catalog task",
}


@dataclass
class Stats:
    period_start: datetime
    period_end: datetime
    total: int
    previous_total: int
    by_type: Counter
    by_category: list[tuple[str, int, int]]  # (category, this week, last week)
    by_day: list[tuple[str, int]]
    by_priority: Counter
    by_group: Counter
    open_count: int
    resolved_count: int
    avg_resolution_hours: float | None
    sla_breaches: list[dict[str, Any]]
    sla_by_name: Counter
    sla_by_group: Counter
    sla_by_priority: Counter
    hardware: list[dict[str, Any]]
    repeat_barcodes: dict[str, list[str]] = field(default_factory=dict)


def split_weeks(tickets: list[dict[str, Any]], days: int, now: datetime | None = None):
    """Split tickets into (this period, previous period) by creation time (UTC)."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    start = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    prev_start = start - timedelta(days=days)
    current, previous = [], []
    for t in tickets:
        created = parse_dt(t.get("sys_created_on", ""))
        if created is None:
            continue
        if created >= start:
            current.append(t)
        elif created >= prev_start:
            previous.append(t)
    return current, previous, start, now


def compute(
    tickets: list[dict[str, Any]],
    breached: list[dict[str, Any]],
    days: int,
    now: datetime | None = None,
) -> tuple[Stats, list[dict[str, Any]]]:
    current, previous, start, end = split_weeks(tickets, days, now)

    def cat(t):
        return t.get("category") or "(none)"

    cur_cat, prev_cat = Counter(map(cat, current)), Counter(map(cat, previous))
    by_category = sorted(
        ((c, cur_cat[c], prev_cat.get(c, 0)) for c in set(cur_cat) | set(prev_cat)),
        key=lambda x: (-x[1], -x[2], x[0]),
    )

    by_day: dict[str, int] = defaultdict(int)
    d = start
    while d.date() <= end.date():
        by_day[d.strftime("%Y-%m-%d")] = 0
        d += timedelta(days=1)
    for t in current:
        by_day[t["sys_created_on"][:10]] += 1

    resolved_hours = []
    open_count = resolved_count = 0
    for t in current:
        created = parse_dt(t.get("sys_created_on", ""))
        done = parse_dt(t.get("resolved_at", "")) or parse_dt(t.get("closed_at", ""))
        if done and created:
            resolved_count += 1
            resolved_hours.append((done - created).total_seconds() / 3600)
        else:
            open_count += 1

    # SLA breaches: task_sla records, plus tickets flagged made_sla=false with no task_sla row.
    by_number = {t["number"]: t for t in current}
    breaches = [b for b in breached if b["number"] in by_number]
    seen = {b["number"] for b in breaches}
    for t in current:
        if str(t.get("made_sla", "")).lower() == "false" and t["number"] not in seen:
            breaches.append({"number": t["number"], "type": t.get("sys_class_name", ""),
                             "sla": "(made_sla = false)", "stage": "", "business_percentage": ""})
    for b in breaches:
        t = by_number[b["number"]]
        b.update(
            category=t.get("category", ""),
            priority=t.get("priority", ""),
            assignment_group=t.get("assignment_group", ""),
            short_description=t.get("short_description", ""),
        )

    hardware = [t for t in current if t.get("is_hardware")]
    barcode_tickets: dict[str, list[str]] = defaultdict(list)
    for t in hardware:
        for code in t.get("barcodes", []):
            barcode_tickets[code].append(t["number"])
    repeat = {k: v for k, v in barcode_tickets.items() if len(v) > 1}

    stats = Stats(
        period_start=start,
        period_end=end,
        total=len(current),
        previous_total=len(previous),
        by_type=Counter(TYPE_LABELS.get(t["table"], t["table"]) for t in current),
        by_category=by_category,
        by_day=sorted(by_day.items()),
        by_priority=Counter(t.get("priority") or "(none)" for t in current),
        by_group=Counter(t.get("assignment_group") or "(unassigned)" for t in current),
        open_count=open_count,
        resolved_count=resolved_count,
        avg_resolution_hours=(sum(resolved_hours) / len(resolved_hours)) if resolved_hours else None,
        sla_breaches=breaches,
        sla_by_name=Counter(b["sla"] for b in breaches),
        sla_by_group=Counter(b["assignment_group"] or "(unassigned)" for b in breaches),
        sla_by_priority=Counter(b["priority"] or "(none)" for b in breaches),
        hardware=hardware,
        repeat_barcodes=repeat,
    )
    return stats, current
