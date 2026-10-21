"""Command line entry point: python -m ticket_analyst"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .config import Settings
from .privacy import sanitize
from .report import build_report, write_csv
from .stats import compute


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="ticket_analyst",
        description="Export the last N days of ServiceNow tickets and write a Word analysis report.",
    )
    p.add_argument("--days", type=int, help="Days to analyse (default SN_DAYS or 7).")
    p.add_argument("--no-ai", action="store_true", help="Skip OpenAI; statistics only.")
    p.add_argument("--sample", action="store_true", help="Use built-in fake tickets instead of ServiceNow.")
    p.add_argument("--output-dir", help="Where to write the report (default OUTPUT_DIR or ./output).")
    return p.parse_args(argv)


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def main(argv=None) -> int:
    args = parse_args(argv)
    s = Settings.from_env()
    days = args.days or s.days
    out_dir = Path(args.output_dir or s.output_dir)

    # 1. Export. Two periods are fetched so this week can be compared with last week.
    if args.sample:
        from .sample_data import make_sample

        log("Using sample data (no ServiceNow call).")
        raw, breached = make_sample(days)
    else:
        missing = s.missing_servicenow()
        if missing:
            print("Missing settings: " + ", ".join(missing) + ". See .env.example.", file=sys.stderr)
            return 2
        from .servicenow import ServiceNowClient

        client = ServiceNowClient(s)
        log(f"Exporting tickets from {s.instance_url} (tables: {', '.join(s.tables)})...")
        raw = client.fetch_tickets(days * 2 + 1)
        log(f"Got {len(raw)} tickets. Fetching breached SLAs...")
        breached = client.fetch_breached_slas(days * 2 + 1)

    # 2. Remove personal information before anything else touches the data.
    tickets = [sanitize(t, s) for t in raw]

    # 3. Statistics.
    stats, current = compute(tickets, breached, days)
    log(f"{stats.total} tickets this period, {len(stats.sla_breaches)} SLA breaches, "
        f"{len(stats.hardware)} hardware tickets.")

    # 4. AI analysis.
    ai = None
    if not args.no_ai and current:
        if not s.openai_api_key:
            print("OPENAI_API_KEY is not set. Set it, or run with --no-ai.", file=sys.stderr)
            return 2
        from .ai import Analyzer

        log(f"Analysing {len(current)} tickets with OpenAI ({s.openai_model})...")
        ai = Analyzer(s).analyze(current, stats)

    # 5. Outputs.
    stamp = f"{stats.period_end:%Y-%m-%d}"
    docx_path = build_report(stats, ai, out_dir / f"IT_ticket_analysis_{stamp}.docx")
    csv_path = write_csv(current, out_dir / f"tickets_{stamp}.csv")
    log(f"Report: {docx_path}")
    log(f"Ticket export (masked): {csv_path}")
    return 0
