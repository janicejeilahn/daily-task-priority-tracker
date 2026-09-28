"""The two halves of the sweep.

collect: read the sheet and Meta, and write
  - plan.json: new lead-form rows, ready to write, plus an empty place for leads Claude adds
    from the inbox and Gmail
  - review.json: inbox threads and duplicates for Claude to read. Never acted on automatically.
apply:   read plan.json, check for duplicates again, give out IDs, and write the rows and
         Master Contacts in one batch. Prints a summary for the report.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .config import BUSINESS_LABELS, MASTER_PREFIX, MASTER_TAB, TABS, TIMEZONE
from .rules import (
    DATE_FMT,
    GENERAL_TAG,
    LeadInput,
    build_lead_row,
    lead_from_meta,
    lead_from_plan,
    safe_cell,
)
from .sheets import TabState, col_letter

TZ = ZoneInfo(TIMEZONE)


def load_state(sheets) -> tuple[dict[str, TabState], TabState]:
    tabs = {key: TabState(name, prefix, sheets.get_values(name)) for key, (name, prefix) in TABS.items()}
    master = TabState(MASTER_TAB, MASTER_PREFIX, sheets.get_values(MASTER_TAB))
    return tabs, master


def sweep_cutoff(hope_path: TabState, today: date) -> date:
    """Since the latest Date Received / Last Contact, but always at least 2 days back."""
    latest = hope_path.latest_date("Date Received", "Last Contact Date") or today
    return min(latest, today - timedelta(days=2))


def _plan_item(lead: LeadInput) -> dict:
    d = dataclasses.asdict(lead)
    d.pop("business")
    d["date_received"] = lead.date_received.strftime(DATE_FMT)
    return d


def collect(sheets, meta, today: date) -> tuple[dict, dict]:
    tabs, _ = load_state(sheets)
    hp = tabs["hope_path"]
    cutoff = sweep_cutoff(hp, today)
    since = datetime.combine(cutoff, time.min, tzinfo=TZ)

    new_hp, duplicates = [], []
    for raw in meta.leads_since(since):
        lead = lead_from_meta(raw)
        found = hp.find(lead.name, lead.phone, lead.email, raw["id"])
        if found is not None:
            duplicates.append({"name": lead.name, "already_on_sheet_as": hp.rows[found][0]})
        else:
            new_hp.append(_plan_item(lead))

    threads = []
    for platform in ("messenger", "instagram"):
        for t in meta.conversations_since(since, platform):
            names = [p["name"] for p in t["participants"]]
            hits = [hp.rows[i][0] for n in names if (i := hp.find(name=n)) is not None]
            t["on_sheet_as"] = hits
            threads.append(t)

    plan = {
        "today": today.strftime(DATE_FMT),
        "new_leads": {"hope_path": new_hp, "upraise": [], "estimatecheck": []},
        "note_updates": [],
    }
    review = {
        "today": today.strftime(DATE_FMT),
        "cutoff": cutoff.strftime(DATE_FMT),
        "next_ids": {key: f"{t.prefix}-{t._next:04d}" for key, t in tabs.items()},
        "lead_form_duplicates_skipped": duplicates,
        "inbox_threads": threads,
        "gmail_query": f"after:{(cutoff - timedelta(days=1)).strftime('%Y/%m/%d')}",
    }
    return plan, review


# --- apply -------------------------------------------------------------------

def _master_row_for(master: TabState, lead: LeadInput, lead_id: str, row: list[str]) -> list[str]:
    tab_name = TABS[lead.business][0]
    tags = lead.interest_tags or [GENERAL_TAG]
    values = {
        "Name": lead.name,
        "Phone": row[3],
        "Email": row[4],
        tab_name: "✓",
        "Interests (what they asked about)": f"{BUSINESS_LABELS[lead.business]}: {'; '.join(tags)}",
        "Priority (any business)": row[8],
        "Needs Cleveland?": "Yes" if lead.needs_cleveland else "",
        "First Inquiry": row[1],
        "Last Contact": "",
        "Latest Outcome": row[14],
        "Lead IDs": lead_id,
        "Email-ready?": "Yes" if row[4] else "No",
    }
    for tag in tags:
        values[tag] = "✓"
    out = [""] * len(master.header)
    for header, v in values.items():
        if header in master.col:
            out[master.col[header]] = safe_cell(v)
    return out


def _merge_master_row(master: TabState, existing: list[str], new: list[str]) -> list[str]:
    """Update an existing contact: tick new boxes, add interests and Lead IDs, keep everything else."""
    merged = list(existing)
    for i, header in enumerate(master.header):
        old, add = existing[i], new[i]
        if not add:
            continue
        if header == "Contact ID":
            continue
        if header == "Interests (what they asked about)":
            merged[i] = add if not old else (old if add in old else f"{old} | {add}")
        elif header == "Lead IDs":
            merged[i] = add if not old else (old if add in old else f"{old}, {add}")
        elif header in ("Priority (any business)", "Needs Cleveland?", "Email-ready?"):
            merged[i] = "Yes" if "Yes" in (old, add) else (old or add)
        elif header in ("First Inquiry", "Last Contact", "Latest Outcome"):
            merged[i] = old or add
        else:  # Name, Phone, Email, ✓ columns: fill blanks only
            merged[i] = old or add
    return merged


def apply(plan: dict, sheets, today: date, dry_run: bool = False) -> dict:
    tabs, master = load_state(sheets)
    writes: list[tuple[str, list[list[str]]]] = []
    master_changes: dict[int, list[str]] = {}
    summary = {"added": {k: [] for k in TABS}, "skipped_duplicates": [], "notes_added": [], "errors": []}

    for business, items in plan.get("new_leads", {}).items():
        if business not in TABS:
            summary["errors"].append(f"Unknown business '{business}'")
            continue
        tab = tabs[business]
        for item in items:
            try:
                lead = lead_from_plan(business, item)
            except (KeyError, ValueError) as e:
                summary["errors"].append(f"{business}: bad entry {item.get('name', '?')}: {e}")
                continue
            meta_id = ""
            if "Meta lead ID: " in lead.notes:
                meta_id = lead.notes.split("Meta lead ID: ", 1)[1].split()[0]
            found = tab.find(lead.name, lead.phone, lead.email, meta_id)
            if found is not None:
                summary["skipped_duplicates"].append(f"{lead.name} (already {tab.rows[found][0]})")
                continue

            lead_id = tab.next_id()
            row = build_lead_row(lead, lead_id, today)
            writes.append((f"'{tab.name}'!A{tab.next_row_number}", [row]))
            tab.append(row)

            new_mc = _master_row_for(master, lead, lead_id, row)
            m = master.find(phone=lead.phone, email=lead.email)
            if m is None:
                new_mc[0] = master.next_id()
                m = master.append(new_mc)
            else:
                master.rows[m] = _merge_master_row(master, master.rows[m], new_mc)
            master_changes[m] = master.rows[m]

            summary["added"][business].append({
                "lead_id": lead_id, "contact_id": master.rows[m][0], "name": lead.name,
                "phone": row[3], "asked": lead.asked_about, "priority": row[8],
                "call_order": row[10], "assigned_to": row[12], "needs_cleveland": row[11],
            })

    for upd in plan.get("note_updates", []):
        tab = tabs.get(upd.get("business", ""))
        if tab is None:
            summary["errors"].append(f"Note update for unknown business: {upd}")
            continue
        notes_col = tab.col.get("Message / Notes")
        idx = next((i for i, r in enumerate(tab.rows) if r[0].strip() == upd.get("lead_id")), None)
        if idx is None or notes_col is None:
            summary["errors"].append(f"Couldn't find {upd.get('lead_id')} on {tab.name}")
            continue
        stamp = today.strftime("%m/%d")
        old = tab.rows[idx][notes_col]
        new = f"{old} | {stamp}: {upd['note']}" if old else f"{stamp}: {upd['note']}"
        tab.rows[idx][notes_col] = safe_cell(new)
        cell = f"'{tab.name}'!{col_letter(notes_col)}{idx + 2}"
        writes.append((cell, [[tab.rows[idx][notes_col]]]))
        summary["notes_added"].append(upd["lead_id"])

    for i, row in sorted(master_changes.items()):
        writes.append((f"'{master.name}'!A{i + 2}", [row]))

    summary["writes"] = len(writes)
    if not dry_run:
        sheets.batch_update(writes)
    summary["dry_run"] = dry_run
    return summary


def format_report(summary: dict) -> str:
    added = summary["added"]
    total = sum(len(v) for v in added.values())
    lines = []
    if total == 0 and not summary["notes_added"]:
        lines.append("No new leads today.")
    else:
        counts = ", ".join(f"{TABS[k][0]} {len(v)}" for k, v in added.items())
        lines.append(f"New leads added: {counts}.")
        thomas = sorted(
            (a for v in added.values() for a in v if a["assigned_to"] == "Thomas"),
            key=lambda a: a["call_order"],
        )
        if thomas:
            lines.append("\nFor Thomas (Call Order A first):")
            lines += [f"- [{a['call_order']}] {a['name']} – {a['phone']} – {a['asked']} – {a['lead_id']}" for a in thomas]
        cleve = [a for v in added.values() for a in v if a["needs_cleveland"]]
        if cleve:
            lines.append("\nNeeds Cleveland:")
            lines += [f"- {a['name']} ({a['lead_id']}): {a['needs_cleveland']}" for a in cleve]
        if summary["notes_added"]:
            lines.append(f"\nNotes added to existing rows: {', '.join(summary['notes_added'])}")
    if summary["skipped_duplicates"]:
        lines.append("\nSkipped (already on the sheet): " + "; ".join(summary["skipped_duplicates"]))
    if summary["errors"]:
        lines.append("\nCouldn't enter:")
        lines += [f"- {e}" for e in summary["errors"]]
    if summary.get("dry_run"):
        lines.append("\n(Dry run: nothing was written.)")
    return "\n".join(lines)
