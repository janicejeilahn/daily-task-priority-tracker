"""Fixed settings for the sweep. Secrets come from environment variables only."""

import os

# Google Sheet "UpRaise_Lead_Tracker".
SHEET_ID = os.environ.get("LEAD_TRACKER_SHEET_ID", "1sluwW6g-9ChIQ9l2trMzeQ-GEwMznzrGi68WCwdZVnM")

# Hope Path Capital Facebook page (the asset_id in the Meta Business Suite links).
META_PAGE_ID = os.environ.get("META_PAGE_ID", "945022918699527")
META_GRAPH_VERSION = os.environ.get("META_GRAPH_VERSION", "v23.0")

# Environment variable names for credentials. Never hard-code the values.
META_TOKEN_ENV = "META_PAGE_TOKEN"
GOOGLE_SA_ENV = "GOOGLE_SA_JSON"  # the service-account key file's JSON content, or a path to it

TIMEZONE = "America/New_York"

# Tab name -> Lead ID prefix.
TABS = {
    "hope_path": ("Hope Path Capital", "HP"),
    "upraise": ("UpRaise Construction", "UR"),
    "estimatecheck": ("EstimateCheck", "EC"),
}
MASTER_TAB = "Master Contacts"
MASTER_PREFIX = "MC"

# Columns A–T of every business tab, in order.
LEAD_COLUMNS = [
    "Lead ID", "Date Received", "Name", "Phone", "Email", "Source", "Asked About",
    "Message / Notes", "Priority", "Priority Reason", "Call Order", "Needs Cleveland?",
    "Assigned To", "Contact Attempts", "Outcome", "Last Contact Date", "Next Action",
    "Next Follow-Up Date", "Lead Type", "Interest Tags",
]

INTEREST_TAGS = [
    "Fix & Flip / Rehab", "Rental / DSCR", "Multifamily", "Commercial", "New Construction",
    "Land", "Refinance / Cash-out", "Single-Family", "Mobile Home / MHP", "Deal source / Partner",
    "Handyman / Repairs", "Estimate Review", "Renovation / Remodel", "Painting",
    "Flooring / Epoxy", "Concrete", "Roofing",
]
GENERAL_TAG = "General / Not specified"

# Short labels used in Master Contacts "Interests" text.
BUSINESS_LABELS = {"hope_path": "Hope Path", "upraise": "UpRaise", "estimatecheck": "EstimateCheck"}
