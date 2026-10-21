# ServiceNow Ticket Analyst

Exports the last 7 days of ServiceNow tickets through the REST API (OAuth), removes
personal information, analyses the tickets with OpenAI, and writes a Word report.

The report covers:

1. **Summary**: key numbers and a short management summary.
2. **Top categories and trends**: this week against last week, tickets per day, by type,
   priority and assignment group.
3. **Recurring issues**: groups of tickets with the same underlying problem, with likely
   root cause and a recommendation (AI).
4. **SLA breaches**: from `task_sla` (plus tickets with `made_sla = false`), by SLA,
   by group, and a list of breached tickets.
5. **Hardware issues**: every hardware ticket with its barcode, and devices that appear in
   more than one ticket.
6. **Recommended actions** (AI).

It also writes a CSV of the masked tickets, which opens in Excel.

## Privacy

Before anything is analysed or written, the tool:

- drops caller, opened by, assigned to and requested for,
- replaces those people's names in the ticket text with `[NAME]`,
- replaces email addresses, phone numbers and IP addresses with `[EMAIL]`, `[PHONE]`, `[IP]`.

Only masked text is sent to OpenAI. Numbers in the report are calculated directly from
ServiceNow, not by the AI. Masking is pattern based, so a name typed into a ticket that
does not belong to one of those people can still slip through. Check a CSV export the
first time you run it.

## Setup

Needs Python 3.10 or newer.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # Windows: copy .env.example .env
```

Then fill in `.env`. You can also set the same names as normal environment variables.

### ServiceNow OAuth

A ServiceNow admin needs to:

1. Go to **System OAuth > Application Registry > New > Create an OAuth API endpoint for
   external clients**. Copy the Client ID and Client Secret into `.env`.
2. Create a service account user (for example `svc_ticket_analyst`) with read access to
   `incident`, `sc_req_item`, `problem`, `change_request` and `task_sla`. The `itil` role,
   or `snc_read_only` plus `itil`, is usually enough. Put its user name and password in `.env`.

If your instance uses the client credentials grant instead, set
`SN_GRANT_TYPE=client_credentials` and leave `SN_USERNAME` / `SN_PASSWORD` empty.

### Hardware barcode

By default the barcode is read from the configuration item's asset tag or serial number,
and any 8 or 14 digit number in the ticket text (set `BARCODE_LENGTHS` to change). If your barcode is stored somewhere else
(for example a custom field `u_barcode`, or `cmdb_ci.u_barcode`), put that field in
`BARCODE_FIELDS`. Change `HARDWARE_CATEGORIES` if your hardware category has another name.

## Run

```bash
python -m ticket_analyst                 # full run
python -m ticket_analyst --no-ai         # statistics only, nothing sent to OpenAI
python -m ticket_analyst --sample        # fake data, no ServiceNow needed
python -m ticket_analyst --days 14       # different period
```

The report is saved as `output/IT_ticket_analysis_<date>.docx`.

## Tests

```bash
pip install pytest
python -m pytest
```
