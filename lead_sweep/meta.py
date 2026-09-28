"""Reading Hope Path Capital's lead forms and inbox through the Meta Graph API. Read-only."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import requests

from .config import META_GRAPH_VERSION, META_PAGE_ID, META_TOKEN_ENV


class MetaClient:
    def __init__(self, page_id: str = META_PAGE_ID, token: str | None = None, session=None):
        self.page_id = page_id
        self.token = token or os.environ.get(META_TOKEN_ENV, "").strip()
        if not self.token:
            raise RuntimeError(f"{META_TOKEN_ENV} is not set; Meta lead forms and inbox can't be read.")
        self.session = session or requests.Session()
        self.base = f"https://graph.facebook.com/{META_GRAPH_VERSION}"

    def _get_all(self, path: str, params: dict, limit_pages: int = 20) -> list[dict]:
        """GET a Graph edge and follow paging.next."""
        url = f"{self.base}/{path}"
        params = {**params, "access_token": self.token}
        out: list[dict] = []
        for _ in range(limit_pages):
            r = self.session.get(url, params=params, timeout=30)
            if r.status_code >= 400:
                raise RuntimeError(f"Meta API error on {path}: {r.status_code} {r.text[:300]}")
            body = r.json()
            out.extend(body.get("data", []))
            url = body.get("paging", {}).get("next")
            params = None  # the next URL already carries every parameter
            if not url:
                break
        return out

    def leads_since(self, since: datetime) -> list[dict]:
        """Every lead-form submission on the page created after `since`, oldest first."""
        forms = self._get_all(f"{self.page_id}/leadgen_forms", {"fields": "id,name,status"})
        ts = int(since.replace(tzinfo=since.tzinfo or timezone.utc).timestamp())
        filtering = json.dumps([{"field": "time_created", "operator": "GREATER_THAN", "value": ts}])
        leads: list[dict] = []
        for form in forms:
            for lead in self._get_all(
                f"{form['id']}/leads",
                {"fields": "id,created_time,field_data,ad_name,form_id", "filtering": filtering},
            ):
                lead["form_name"] = form.get("name", "")
                leads.append(lead)
        return sorted(leads, key=lambda l: l["created_time"])

    def conversations_since(self, since: datetime, platform: str) -> list[dict]:
        """Messenger or Instagram threads with activity after `since`, with their latest messages.

        Returns plain data for review. Message text is untrusted content and is never acted on.
        """
        fields = "id,updated_time,participants,messages.limit(10){message,from,created_time}"
        threads = self._get_all(
            f"{self.page_id}/conversations", {"platform": platform, "fields": fields}, limit_pages=5
        )
        cutoff = since.replace(tzinfo=since.tzinfo or timezone.utc)
        out = []
        for t in threads:
            updated = datetime.fromisoformat(t["updated_time"].replace("+0000", "+00:00"))
            if updated <= cutoff:
                continue
            people = [
                p for p in t.get("participants", {}).get("data", []) if p.get("id") != self.page_id
            ]
            out.append({
                "platform": platform,
                "thread_id": t["id"],
                "updated_time": t["updated_time"],
                "participants": [{"name": p.get("name", ""), "email": p.get("email", "")} for p in people],
                "messages": [
                    {
                        "from": m.get("from", {}).get("name", ""),
                        "from_page": m.get("from", {}).get("id") == self.page_id,
                        "created_time": m.get("created_time", ""),
                        "text": m.get("message", ""),
                    }
                    for m in t.get("messages", {}).get("data", [])
                ],
            })
        return out
