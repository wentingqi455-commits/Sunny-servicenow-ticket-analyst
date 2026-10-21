"""Fake tickets for trying the tool without ServiceNow. Contains fake personal data on purpose
so you can see the masking work."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

PEOPLE = ["Alice Johnson", "Bob Smith", "Chen Wei", "Priya Patel", "Marco Rossi", "Sara Lee"]
GROUPS = ["Service Desk", "Desktop Support", "Network Team", "Identity & Access", "Apps Support"]
PRIORITIES = ["1 - Critical", "2 - High", "3 - Moderate", "4 - Low"]

TEMPLATES = [
    # (table, category, subcategory, short, description, group, weight)
    ("incident", "Hardware", "Laptop", "Laptop will not power on",
     "Hi {first}, laptop barcode {barcode} does not turn on after the BIOS update. Call me on +44 7700 900123.",
     "Desktop Support", 6),
    ("incident", "Hardware", "Docking station", "Docking station monitors flicker",
     "Dock {barcode} at desk 4.12, external screens flicker. Contact {email}.", "Desktop Support", 4),
    ("incident", "Hardware", "Printer", "Printer jams on floor 3",
     "Printer with barcode {barcode} jams on every job. Reported by {name}.", "Desktop Support", 3),
    ("incident", "Network", "VPN", "VPN disconnects every 10 minutes",
     "GlobalProtect drops connection from home. IP 10.20.30.{n}. User {name}, ext 555-123-4567.",
     "Network Team", 7),
    ("incident", "Network", "Wi-Fi", "Wi-Fi slow in building B",
     "Wi-Fi in building B is very slow since Monday.", "Network Team", 3),
    ("incident", "Software", "Outlook", "Outlook crashes when opening shared mailbox",
     "Outlook 365 crashes when {name} opens the Finance shared mailbox. Email {email}.",
     "Apps Support", 6),
    ("incident", "Software", "Teams", "Teams meeting audio not working",
     "No audio in Teams meetings after update.", "Apps Support", 3),
    ("incident", "Inquiry / Help", "Password", "Account locked out",
     "Dear Service Desk, I am locked out again. Thanks {first}", "Identity & Access", 8),
    ("sc_req_item", "New laptop", "", "Request new laptop for new starter",
     "New starter {name} joins on Monday.", "Desktop Support", 4),
    ("sc_req_item", "Software install", "", "Install Visio",
     "Please install Visio for {name}.", "Service Desk", 4),
    ("problem", "Network", "VPN", "Recurring VPN disconnects",
     "Multiple users report VPN drops.", "Network Team", 1),
    ("change_request", "Software", "", "Deploy Outlook patch",
     "Patch for shared mailbox crash.", "Apps Support", 1),
]


def make_sample(days: int = 7, seed: int = 7):
    rnd = random.Random(seed)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    weights = [t[-1] for t in TEMPLATES]
    barcodes = [str(rnd.randint(10_000_000, 99_999_999)) for _ in range(10)]
    tickets, breached = [], []
    for i in range(int(days * 2 * 9)):
        table, cat, sub, short, desc, group, _ = rnd.choices(TEMPLATES, weights)[0]
        # last week a bit quieter, and VPN problems mostly this week
        age = rnd.uniform(0, days * 2)
        if "VPN" in short and age > days and rnd.random() < 0.6:
            age -= days
        created = now - timedelta(days=age)
        name = rnd.choice(PEOPLE)
        first = name.split()[0]
        prefix = {"incident": "INC", "sc_req_item": "RITM", "problem": "PRB", "change_request": "CHG"}[table]
        resolved = created + timedelta(hours=rnd.uniform(0.5, 72)) if rnd.random() < 0.7 else None
        if resolved and resolved > now:
            resolved = None
        made_sla = "false" if rnd.random() < 0.12 else "true"
        t = {
            "table": table,
            "sys_class_name": table,
            "number": f"{prefix}{1000000 + i:07d}",
            "short_description": short,
            "description": desc.format(
                first=first, name=name, n=rnd.randint(2, 250),
                email=first.lower() + "." + name.split()[1].lower() + "@example.com",
                barcode=rnd.choice(barcodes),
            ),
            "category": cat,
            "subcategory": sub,
            "priority": rnd.choices(PRIORITIES, [1, 3, 8, 4])[0],
            "state": "Resolved" if resolved else rnd.choice(["New", "In Progress", "On Hold"]),
            "assignment_group": group,
            "cmdb_ci": "",
            "sys_created_on": created.strftime("%Y-%m-%d %H:%M:%S"),
            "resolved_at": resolved.strftime("%Y-%m-%d %H:%M:%S") if resolved else "",
            "closed_at": "",
            "made_sla": made_sla,
            "caller_id": name,
            "opened_by": name,
            "assigned_to": rnd.choice(PEOPLE),
        }
        tickets.append(t)
        if made_sla == "false":
            breached.append({
                "number": t["number"], "type": table,
                "sla": rnd.choice(["P3 resolution (3 days)", "P2 resolution (8h)", "Response (4h)"]),
                "stage": "Completed" if resolved else "In progress", "business_percentage": "112",
            })
    return tickets, breached
