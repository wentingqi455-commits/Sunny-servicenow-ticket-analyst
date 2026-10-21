from datetime import datetime

from ticket_analyst import ai as ai_mod
from ticket_analyst.cli import main
from ticket_analyst.config import Settings
from ticket_analyst.privacy import mask_text, sanitize
from ticket_analyst.sample_data import make_sample
from ticket_analyst.servicenow import normalize
from ticket_analyst.stats import compute


def settings(**kw):
    s = Settings(
        hardware_categories=["hardware"],
        barcode_fields=["cmdb_ci.asset_tag"],
        barcode_lengths=[8, 14],
    )
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def test_mask_text_removes_contact_details_but_keeps_dates():
    text = ("Mail jane.doe@corp.com or call +44 7700 900123 / (02) 9876-5432. "
            "Host 10.1.2.3. Seen on 2026-10-20. Thanks Jane")
    out = mask_text(text)
    assert "jane.doe" not in out and "7700" not in out and "9876" not in out
    assert "10.1.2.3" not in out
    assert "2026-10-20" in out
    assert out.endswith("Thanks [NAME]")
    assert mask_text("Dear Service Desk, help") == "Dear Service Desk, help"


def test_sanitize_extracts_barcode_then_drops_people():
    t = {
        "number": "INC0010001",
        "category": "Hardware",
        "subcategory": "Laptop",
        "short_description": "Laptop 12345678 broken",
        "description": "Bob Smith says laptop 12345678 is dead, version 1.2.3456789",
        "caller_id": "Bob Smith",
        "assigned_to": "Ann Lee",
        "cmdb_ci.asset_tag": "12345678901234",
    }
    out = sanitize(t, settings())
    assert out["is_hardware"]
    assert out["barcodes"] == ["12345678901234", "12345678"]
    assert "Bob" not in out["description"] and "Smith" not in out["description"]
    assert "caller_id" not in out and "assigned_to" not in out
    assert "12345678" in out["description"]  # barcode stays in the text


def test_non_hardware_gets_no_barcode():
    out = sanitize({"number": "INC1", "category": "Network", "short_description": "id 1234567"}, settings())
    assert out["barcodes"] == []


def test_normalize_uses_display_values_and_raw_dates():
    raw = {
        "number": {"value": "INC1", "display_value": "INC1"},
        "category": {"value": "hardware", "display_value": "Hardware"},
        "sys_created_on": {"value": "2026-10-20 08:00:00", "display_value": "20/10/2026 10:00"},
    }
    t = normalize(raw, "incident")
    assert t["category"] == "Hardware"
    assert t["sys_created_on"] == "2026-10-20 08:00:00"


def test_stats_on_sample():
    raw, breached = make_sample(7)
    tickets = [sanitize(t, settings()) for t in raw]
    stats, current = compute(tickets, breached, 7)
    assert stats.total == len(current) > 0
    assert stats.previous_total > 0
    assert sum(n for _, n in stats.by_day) == stats.total
    assert all(b["number"] in {t["number"] for t in current} for b in stats.sla_breaches)
    assert stats.hardware and all(t["barcodes"] for t in stats.hardware)


def test_clean_result_drops_made_up_ticket_numbers():
    res = ai_mod.clean_result(
        {"recurring_issues": [{"title": "x", "ticket_numbers": ["INC1", "FAKE"]},
                              {"title": "y", "ticket_numbers": ["NOPE"]}]},
        {"INC1"},
    )
    assert res["recurring_issues"] == [{"title": "x", "ticket_numbers": ["INC1"]}]
    assert res["recommendations"] == []


def test_end_to_end_with_fake_openai(tmp_path, monkeypatch):
    sent = []

    def fake_init(self, s):
        self.model = "fake"

    def fake_ask(self, prompt):
        sent.append(prompt)
        if "Return JSON: {\"themes\"" in prompt:
            return {"themes": [{"title": "VPN drops", "ticket_numbers": ["INC1000002"]}]}
        return {
            "executive_summary": "Busy week.",
            "trend_insights": ["VPN up."],
            "recurring_issues": [{"title": "VPN drops", "ticket_numbers": ["INC1000002"],
                                  "root_cause": "Gateway", "recommendation": "Fix it"}],
            "sla_insights": ["Desktop Support breached most."],
            "hardware_insights": ["One laptop came back twice."],
            "recommendations": ["Patch VPN gateway."],
        }

    monkeypatch.setattr(ai_mod.Analyzer, "__init__", fake_init)
    monkeypatch.setattr(ai_mod.Analyzer, "_ask", fake_ask)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    assert main(["--sample", "--output-dir", str(tmp_path)]) == 0
    assert list(tmp_path.glob("*.docx")) and list(tmp_path.glob("*.csv"))
    # nothing personal reached the AI
    blob = "\n".join(sent)
    for leak in ("Alice", "Johnson", "@example.com", "7700", "555-123"):
        assert leak not in blob


def test_barcode_only_8_or_14_digits():
    t = {"number": "INC2", "category": "Hardware",
         "short_description": "codes 1234567 12345678 123456789 12345678901234 123456789012345"}
    assert sanitize(t, settings())["barcodes"] == ["12345678", "12345678901234"]
