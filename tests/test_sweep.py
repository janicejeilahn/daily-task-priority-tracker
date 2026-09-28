from datetime import date, datetime, timedelta

from lead_sweep.config import LEAD_COLUMNS
from lead_sweep.rules import (
    LeadInput,
    build_lead_row,
    guess_interest_tags,
    lead_from_meta,
    looks_large_or_unusual,
    normalize_phone,
    parse_under_contract,
)
from lead_sweep.sheets import TabState, col_letter
from lead_sweep.sweep import apply, collect, format_report, sweep_cutoff

TODAY = date(2026, 9, 28)

MASTER_HEADER = [
    "Contact ID", "Name", "Phone", "Email", "EstimateCheck", "Hope Path Capital",
    "UpRaise Construction", "Interests (what they asked about)", "Priority (any business)",
    "Needs Cleveland?", "First Inquiry", "Last Contact", "Latest Outcome", "Lead IDs",
    "Email-ready?", "Fix & Flip / Rehab", "Rental / DSCR", "Multifamily", "Commercial",
    "New Construction", "Land", "Refinance / Cash-out", "Single-Family", "Mobile Home / MHP",
    "Deal source / Partner", "Handyman / Repairs", "Estimate Review", "Renovation / Remodel",
    "Painting", "Flooring / Epoxy", "Concrete",
]


def hp_row(lead_id, name, phone="", email="", received="09/25/2026", notes=""):
    row = [""] * len(LEAD_COLUMNS)
    row[0], row[1], row[2], row[3], row[4], row[7] = lead_id, received, name, phone, email, notes
    return row


class FakeSheets:
    def __init__(self):
        self.tabs = {
            "Hope Path Capital": [LEAD_COLUMNS,
                                  hp_row("HP-0270", "Robert", "202-579-9791", "robert@x.com"),
                                  hp_row("HP-0271", "Candy CRAIG", "555-111-2222", "", "09/25/2026")],
            "UpRaise Construction": [LEAD_COLUMNS, hp_row("UR-0005", "Eve and Mark")],
            "EstimateCheck": [LEAD_COLUMNS],
            "Master Contacts": [MASTER_HEADER,
                                ["MC-0275", "Candy CRAIG", "555-111-2222", "", "", "✓", "",
                                 "Hope Path: Rental / DSCR", "Yes", "", "09/25/2026", "", "",
                                 "HP-0271", "No"] + [""] * 16],
        }
        self.writes = []

    def get_values(self, tab):
        return [list(r) for r in self.tabs[tab]]

    def batch_update(self, data):
        self.writes.extend(data)


def meta_lead(lead_id, name, phone, email, deal, contract, cash, created="2026-09-27T15:00:00+0000"):
    return {
        "id": lead_id,
        "created_time": created,
        "field_data": [
            {"name": "full_name", "values": [name]},
            {"name": "phone_number", "values": [phone]},
            {"name": "email", "values": [email]},
            {"name": "what_kind_of_deal_are_you_working_on?", "values": [deal]},
            {"name": "is_it_under_contract?", "values": [contract]},
            {"name": "how_much_cash_are_you_planning_to_bring?", "values": [cash]},
        ],
    }


class FakeMeta:
    def __init__(self, leads, threads=()):
        self.leads, self.threads = leads, list(threads)

    def leads_since(self, since):
        return self.leads

    def conversations_since(self, since, platform):
        return [t for t in self.threads if t["platform"] == platform]


# --- rules ----------------------------------------------------------------------

def test_normalize_phone():
    assert normalize_phone("+18144903062") == "814-490-3062"
    assert normalize_phone("(707) 495-0227") == "707-495-0227"
    assert normalize_phone("") == ""


def test_under_contract():
    assert parse_under_contract("yes")
    assert parse_under_contract("Under contract")
    assert parse_under_contract("Already own")
    assert not parse_under_contract("not yet but will be")
    assert not parse_under_contract("No")
    assert not parse_under_contract("Next deal")


def test_interest_tags_match_existing_rows():
    assert guess_interest_tags("multi family") == ["Multifamily"]
    assert guess_interest_tags("rental investment") == ["Rental / DSCR"]
    assert guess_interest_tags("Fix and flip") == ["Fix & Flip / Rehab"]
    assert guess_interest_tags("build") == ["New Construction"]
    assert guess_interest_tags("0") == ["General / Not specified"]


def test_needs_cleveland_detection():
    assert looks_large_or_unusual("commercial") == "commercial deal"
    assert looks_large_or_unusual("looking for $1,200,000 purchase") == "large deal ($1M+)"
    assert looks_large_or_unusual("fix and flip 35000") == ""


def test_call_order_and_follow_up():
    base = dict(business="hope_path", name="A B", source="x", priority=True, phone="8145550000")
    fresh = build_lead_row(LeadInput(date_received=TODAY - timedelta(days=3), **base), "HP-1", TODAY)
    mid = build_lead_row(LeadInput(date_received=TODAY - timedelta(days=20), **base), "HP-2", TODAY)
    old = build_lead_row(LeadInput(date_received=TODAY - timedelta(days=60), **base), "HP-3", TODAY)
    old_call = build_lead_row(
        LeadInput(date_received=TODAY - timedelta(days=60), asked_for_call=True, **base), "HP-4", TODAY)
    assert (fresh[10], fresh[17]) == ("A", "09/28/2026")
    assert (mid[10], mid[17]) == ("B", "09/29/2026")
    assert (old[10], old[17]) == ("C", "10/01/2026")
    assert old_call[10] == "A"
    assert fresh[12] == "Thomas" and fresh[16] == "Call" and fresh[14] == "Not yet contacted"


def test_assignment_never_josh_and_messenger_only():
    lead = LeadInput(business="hope_path", name="TJ", date_received=TODAY, source="Facebook Messenger",
                     priority=True, messenger_only=True)
    row = build_lead_row(lead, "HP-9", TODAY)
    assert row[12] == "Janice (Messenger)"
    lead.needs_cleveland = "deal source"
    assert build_lead_row(lead, "HP-9", TODAY)[12] == "Cleveland"


def test_formula_text_is_neutralized():
    lead = LeadInput(business="hope_path", name="=HYPERLINK(\"x\")", date_received=TODAY, source="x")
    assert build_lead_row(lead, "HP-1", TODAY)[2].startswith("'=")


def test_lead_from_meta():
    lead = lead_from_meta(meta_lead("111", "Marta Salazar", "+18455551234", "m@x.com",
                                    "Fix and flip", "Under contract", "40k"))
    assert lead.phone == "+18455551234"
    assert lead.under_contract
    assert lead.priority_reason == "Requested financing info (lead form); under contract"
    assert lead.notes.endswith("Meta lead ID: 111")
    assert lead.date_received == date(2026, 9, 27)


# --- sheet state ------------------------------------------------------------------

def test_tab_state_ids_and_dedupe():
    t = TabState("Hope Path Capital", "HP", FakeSheets().get_values("Hope Path Capital"))
    assert t.next_id() == "HP-0272"
    assert t.next_row_number == 4
    assert t.find(email="ROBERT@x.com") == 0
    assert t.find(phone="+1 (555) 111-2222") == 1
    assert t.find(name="candy craig") == 1
    assert t.find(name="Robert") is None  # one-word names don't count as a match


def test_col_letter():
    assert [col_letter(i) for i in (0, 7, 25, 26, 30)] == ["A", "H", "Z", "AA", "AE"]


def test_cutoff_is_at_least_two_days_back():
    t = TabState("Hope Path Capital", "HP", FakeSheets().get_values("Hope Path Capital"))
    assert sweep_cutoff(t, TODAY) == date(2026, 9, 25)
    assert sweep_cutoff(t, date(2026, 9, 26)) == date(2026, 9, 24)


# --- end to end -------------------------------------------------------------------

def test_collect_then_apply():
    sheets = FakeSheets()
    meta = FakeMeta(
        [
            meta_lead("111", "Marta Salazar", "+18455551234", "marta@x.com", "Fix and flip", "yes", "40k"),
            meta_lead("112", "Daniel Scott", "+15551112222", "d@x.com", "rental", "no", "20k"),  # same phone as Candy
        ],
        [{"platform": "messenger", "thread_id": "t1", "updated_time": "2026-09-28T10:00:00+0000",
          "participants": [{"name": "Candy CRAIG", "email": ""}], "messages": []}],
    )
    plan, review = collect(sheets, meta, TODAY)
    assert [l["name"] for l in plan["new_leads"]["hope_path"]] == ["Marta Salazar"]
    assert review["lead_form_duplicates_skipped"] == [{"name": "Daniel Scott", "already_on_sheet_as": "HP-0271"}]
    assert review["inbox_threads"][0]["on_sheet_as"] == ["HP-0271"]
    assert review["next_ids"]["hope_path"] == "HP-0272"

    # Claude adds one UpRaise lead from Gmail and a note on an existing row.
    plan["new_leads"]["upraise"].append({
        "name": "Pat Lee", "date_received": "09/27/2026", "source": "Email (info@upeusa.com)",
        "asked_about": "Quote – bathroom remodel", "email": "pat@x.com", "priority": True,
        "priority_reason": "Asked for estimate", "lead_type": "Customer inquiry",
        "interest_tags": ["Renovation / Remodel", "Not a real tag"],
    })
    plan["note_updates"].append({"business": "hope_path", "lead_id": "HP-0271", "note": "Replied by email"})

    summary = apply(plan, sheets, TODAY)
    assert summary["errors"] == []
    written = dict(sheets.writes)

    hp = written["'Hope Path Capital'!A4"][0]
    assert hp[:5] == ["HP-0272", "09/27/2026", "Marta Salazar", "845-555-1234", "marta@x.com"]
    assert hp[10:13] == ["A", "", "Thomas"]

    ur = written["'UpRaise Construction'!A3"][0]
    assert ur[0] == "UR-0006" and ur[12] == "" and ur[16] == "Email for phone number"
    assert ur[19] == "Renovation / Remodel"

    assert written["'Hope Path Capital'!H3"] == [["09/28: Replied by email"]]

    mc_new = written["'Master Contacts'!A3"][0]
    assert mc_new[0] == "MC-0276" and mc_new[5] == "✓" and mc_new[13] == "HP-0272"
    assert mc_new[MASTER_HEADER.index("Fix & Flip / Rehab")] == "✓"
    assert written["'Master Contacts'!A4"][0][0] == "MC-0277"

    report = format_report(summary)
    assert "[A] Marta Salazar – 845-555-1234" in report


def test_apply_merges_existing_master_contact_and_dry_run_writes_nothing():
    sheets = FakeSheets()
    plan = {"new_leads": {"upraise": [{
        "name": "Candy Craig Jr", "date_received": "09/27/2026", "source": "Email (info@upeusa.com)",
        "phone": "555-111-2222", "email": "candy@x.com", "priority": True,
        "priority_reason": "Asked for estimate", "interest_tags": ["Painting"]}]}}

    summary = apply(plan, sheets, TODAY, dry_run=True)
    assert sheets.writes == [] and summary["writes"] == 2

    apply(plan, sheets, TODAY)
    mc = dict(sheets.writes)["'Master Contacts'!A2"][0]
    assert mc[0] == "MC-0275"
    assert mc[5] == "✓" and mc[6] == "✓"
    assert mc[7] == "Hope Path: Rental / DSCR | UpRaise: Painting"
    assert mc[13] == "HP-0271, UR-0006"
    assert mc[3] == "candy@x.com"


def test_apply_skips_duplicates_on_second_run():
    sheets = FakeSheets()
    plan = {"new_leads": {"hope_path": [{
        "name": "Robert Jones", "date_received": "09/27/2026", "source": "x", "email": "robert@x.com"}]}}
    summary = apply(plan, sheets, TODAY)
    assert summary["skipped_duplicates"] == ["Robert Jones (already HP-0270)"]
    assert format_report(summary).startswith("No new leads today.")
