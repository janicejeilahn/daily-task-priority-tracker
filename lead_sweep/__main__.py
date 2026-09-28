"""Command line.

  python -m lead_sweep check                   # confirm credentials and access, no writes
  python -m lead_sweep collect [--out DIR]     # writes DIR/plan.json and DIR/review.json
  python -m lead_sweep apply PLAN [--dry-run]  # writes the plan's rows to the sheet
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .sweep import TZ, apply, collect, format_report, load_state


def _today():
    return datetime.now(TZ).date()


def cmd_check(_args) -> int:
    from .config import MASTER_TAB, TABS
    from .meta import MetaClient
    from .sheets import SheetsClient

    ok = True
    try:
        tabs, master = load_state(SheetsClient())
        for t in [*tabs.values(), master]:
            print(f"✓ Sheet tab '{t.name}': {len(t.rows)} rows, next ID {t.prefix}-{t._next:04d}")
    except Exception as e:  # noqa: BLE001 - report every failure plainly
        ok = False
        print(f"✗ Google Sheet: {e}")
    try:
        meta = MetaClient()
        forms = meta._get_all(f"{meta.page_id}/leadgen_forms", {"fields": "id,name,status"})
        print(f"✓ Meta lead forms: {len(forms)} found")
        meta._get_all(f"{meta.page_id}/conversations", {"platform": "messenger", "fields": "id"}, limit_pages=1)
        print("✓ Meta Messenger inbox readable")
        meta._get_all(f"{meta.page_id}/conversations", {"platform": "instagram", "fields": "id"}, limit_pages=1)
        print("✓ Meta Instagram inbox readable")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"✗ Meta: {e}")
    return 0 if ok else 1


def cmd_collect(args) -> int:
    from .meta import MetaClient
    from .sheets import SheetsClient

    plan, review = collect(SheetsClient(), MetaClient(), _today())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False))
    (out / "review.json").write_text(json.dumps(review, indent=2, ensure_ascii=False))
    print(f"Lead-form leads ready to add: {len(plan['new_leads']['hope_path'])}")
    print(f"Already on the sheet: {len(review['lead_form_duplicates_skipped'])}")
    print(f"Inbox threads to review: {len(review['inbox_threads'])}")
    print(f"Wrote {out / 'plan.json'} and {out / 'review.json'}")
    return 0


def cmd_apply(args) -> int:
    from .sheets import SheetsClient

    plan = json.loads(Path(args.plan).read_text())
    summary = apply(plan, SheetsClient(), _today(), dry_run=args.dry_run)
    Path(args.plan).with_name("summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(format_report(summary))
    return 1 if summary["errors"] else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="lead_sweep")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    c = sub.add_parser("collect")
    c.add_argument("--out", default="sweep_out")
    c.set_defaults(fn=cmd_collect)
    a = sub.add_parser("apply")
    a.add_argument("plan")
    a.add_argument("--dry-run", action="store_true")
    a.set_defaults(fn=cmd_apply)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
