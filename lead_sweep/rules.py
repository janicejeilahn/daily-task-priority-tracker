"""The sweep's row-filling rules (see daily_lead_sweep_task.md, Step 3), as plain functions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .config import GENERAL_TAG, INTEREST_TAGS

DATE_FMT = "%m/%d/%Y"


@dataclass
class LeadInput:
    """One new lead, before it gets a Lead ID. Unknown fields stay empty."""

    business: str  # "hope_path" | "upraise" | "estimatecheck"
    name: str
    date_received: date
    source: str
    asked_about: str = ""
    notes: str = ""
    phone: str = ""
    email: str = ""
    lead_type: str = ""
    interest_tags: list[str] = field(default_factory=list)
    # Facts that drive the rules:
    priority: bool = False
    priority_reason: str = ""
    under_contract: bool = False
    asked_for_call: bool = False
    messenger_only: bool = False
    needs_cleveland: str = ""  # "" or a short reason
    next_action: str = ""  # override; default is Call / Email for phone number


def normalize_phone(raw: str) -> str:
    """'+1 (814) 490-3062' -> '814-490-3062'. Leaves non-US numbers as given."""
    raw = (raw or "").strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return raw


def phone_digits(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    return digits[-10:] if len(digits) >= 10 else digits


def parse_under_contract(answer: str) -> bool:
    a = (answer or "").strip().lower()
    if not a or a.startswith("no") or "not" in a:
        return False
    return bool(re.search(r"\byes\b|contract|already own|already bought|\bown\b|closed", a))


_TAG_PATTERNS = [
    ("Fix & Flip / Rehab", r"fix|flip|rehab|renovat"),
    ("Rental / DSCR", r"rent|dscr|buy and hold|buy & hold"),
    ("Multifamily", r"multi|duplex|triplex|fourplex|quadplex|\d+\s*units?|apartment"),
    ("Commercial", r"commercial|retail|office|warehouse|mixed.?use|industrial"),
    ("New Construction", r"build|construction|ground.?up|new home"),
    ("Land", r"\bland\b|\blots?\b|acre"),
    ("Refinance / Cash-out", r"refi|cash.?out|equity loan"),
    ("Single-Family", r"single|sfr|\bhouse\b|\bhome\b"),
    ("Mobile Home / MHP", r"mobile|manufactured|\bmhp\b|trailer"),
    ("Deal source / Partner", r"wholesal|partner|joint venture|\bjv\b"),
]


def guess_interest_tags(text: str) -> list[str]:
    t = (text or "").lower()
    tags = [tag for tag, pattern in _TAG_PATTERNS if re.search(pattern, t)]
    return tags or [GENERAL_TAG]


def looks_large_or_unusual(text: str) -> str:
    """Return a Needs-Cleveland reason for $1M+, commercial or partnership/equity deals, else ''."""
    t = (text or "").lower()
    if re.search(r"commercial|mixed.?use|warehouse|industrial|retail|office building", t):
        return "commercial deal"
    if re.search(r"partner|equity|joint venture|\bjv\b", t):
        return "partnership / equity"
    if re.search(r"\d+(\.\d+)?\s*(m\b|mm\b|mil|million)|\$?\s*\d{1,3}(,\d{3}){2,}", t):
        return "large deal ($1M+)"
    return ""


def call_order(lead: LeadInput, today: date) -> str:
    age = (today - lead.date_received).days
    if age <= 14 or lead.under_contract or lead.asked_for_call:
        return "A"
    if age <= 45:
        return "B"
    return "C"


def assigned_to(lead: LeadInput) -> str:
    # Needs-Cleveland items go to Cleveland; never assign Josh.
    if lead.needs_cleveland:
        return "Cleveland"
    if lead.priority and lead.phone:
        return "Thomas"
    if lead.messenger_only:
        return "Janice (Messenger)"
    return ""


def follow_up_date(order: str, today: date) -> date:
    return today + timedelta(days={"A": 0, "B": 1, "C": 3}[order])


def safe_cell(value: str) -> str:
    """Stop text from outside (names, form answers) from being read as a formula."""
    if value and value[0] in "=+-@":
        return "'" + value
    return value


def build_lead_row(lead: LeadInput, lead_id: str, today: date) -> list[str]:
    """Columns A–T for a new lead."""
    order = call_order(lead, today)
    if lead.next_action:
        next_action = lead.next_action
    elif lead.phone:
        next_action = "Call"
    elif lead.email:
        next_action = "Email for phone number"
    elif lead.messenger_only:
        next_action = "Get phone number via Messenger"
    else:
        next_action = ""
    tags = lead.interest_tags or [GENERAL_TAG]
    row = [
        lead_id,
        lead.date_received.strftime(DATE_FMT),
        lead.name,
        normalize_phone(lead.phone),
        lead.email.strip(),
        lead.source,
        lead.asked_about,
        lead.notes,
        "Yes" if lead.priority else "No",
        lead.priority_reason if lead.priority else "",
        order,
        f"Yes – {lead.needs_cleveland}" if lead.needs_cleveland else "",
        assigned_to(lead),
        "",  # Contact Attempts
        "Not yet contacted",
        "",  # Last Contact Date
        next_action,
        follow_up_date(order, today).strftime(DATE_FMT),
        lead.lead_type,
        "; ".join(tags),
    ]
    return [safe_cell(v) for v in row]


# --- Meta lead forms -------------------------------------------------------

def _answer(field_data: list[dict], *keywords: str) -> str:
    """Find a form answer whose field name contains all the keywords."""
    for f in field_data:
        name = f.get("name", "").lower()
        if all(k in name for k in keywords):
            return ", ".join(v for v in f.get("values", []) if v)
    return ""


def lead_from_meta(meta_lead: dict) -> LeadInput:
    """Turn one Graph API lead (id, created_time, field_data) into a Hope Path LeadInput."""
    fd = meta_lead.get("field_data", [])
    name = _answer(fd, "full_name") or " ".join(
        x for x in (_answer(fd, "first_name"), _answer(fd, "last_name")) if x
    )
    deal = _answer(fd, "deal")
    contract = _answer(fd, "contract")
    cash = _answer(fd, "cash")
    created = datetime.fromisoformat(meta_lead["created_time"].replace("+0000", "+00:00"))
    under = parse_under_contract(contract)

    notes = f"Deal type: {deal} | Under contract?: {contract} | Cash to bring: {cash}"
    notes += f" | Meta lead ID: {meta_lead['id']}"
    reason = "Requested financing info (lead form)" + ("; under contract" if under else "")
    return LeadInput(
        business="hope_path",
        name=name.strip(),
        date_received=created.date(),
        source="Facebook Lead Ad (instant form)",
        asked_about=f"Financing – {deal}" if deal else "Financing",
        notes=notes,
        phone=_answer(fd, "phone"),
        email=_answer(fd, "email"),
        lead_type="Borrower inquiry",
        interest_tags=guess_interest_tags(deal),
        priority=True,
        priority_reason=reason,
        under_contract=under,
        needs_cleveland=looks_large_or_unusual(f"{deal} {cash}"),
    )


def lead_from_plan(business: str, item: dict) -> LeadInput:
    """Turn one entry Claude wrote into the plan file into a LeadInput."""
    return LeadInput(
        business=business,
        name=item["name"].strip(),
        date_received=datetime.strptime(item["date_received"], DATE_FMT).date(),
        source=item.get("source", ""),
        asked_about=item.get("asked_about", ""),
        notes=item.get("notes", ""),
        phone=item.get("phone", ""),
        email=item.get("email", ""),
        lead_type=item.get("lead_type", ""),
        interest_tags=[t for t in item.get("interest_tags", []) if t in INTEREST_TAGS or t == GENERAL_TAG],
        priority=bool(item.get("priority", False)),
        priority_reason=item.get("priority_reason", ""),
        under_contract=bool(item.get("under_contract", False)),
        asked_for_call=bool(item.get("asked_for_call", False)),
        messenger_only=bool(item.get("messenger_only", False)),
        needs_cleveland=item.get("needs_cleveland", ""),
        next_action=item.get("next_action", ""),
    )
