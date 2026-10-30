import os
from datetime import datetime, time, timedelta, timezone
from urllib.parse import urlencode

import requests

BASE = "https://api.calendly.com"


class CalendlyError(Exception):
    pass


def _headers():
    token = os.getenv("CALENDLY_TOKEN")
    if not token:
        raise CalendlyError("CALENDLY_TOKEN is missing in .env")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _get(path, params=None):
    r = requests.get(f"{BASE}{path}", headers=_headers(), params=params, timeout=20)
    if not r.ok:
        raise CalendlyError(f"Calendly {r.status_code}: {r.text[:300]}")
    return r.json()


def get_available_slots(event_type_uri, day, tz):
    """Open slots for one local calendar day. Calendly allows max a 7-day range."""
    start_local = datetime.combine(day, time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    earliest = datetime.now(timezone.utc) + timedelta(minutes=2)  # start must be in future
    start = max(start_local.astimezone(timezone.utc), earliest)
    end = end_local.astimezone(timezone.utc)
    if start >= end:
        return []
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    data = _get(
        "/event_type_available_times",
        {
            "event_type": event_type_uri,
            "start_time": start.strftime(fmt),
            "end_time": end.strftime(fmt),
        },
    )
    return [
        {"start": s["start_time"], "url": s.get("scheduling_url")}
        for s in data.get("collection", [])
        if s.get("status") == "available"
    ]


def prefilled_link(slot_url, name, email):
    sep = "&" if "?" in slot_url else "?"
    return slot_url + sep + urlencode({"name": name, "email": email})


def get_event_type():
    """Free plan = one event type, so just take the first active one."""
    me = _get("/users/me")["resource"]
    data = _get("/event_types", {"user": me["uri"], "active": "true"})
    types = data.get("collection", [])
    if not types:
        raise CalendlyError("No active event type found in your Calendly account.")
    et = types[0]
    return {
        "uri": et["uri"],
        "name": et["name"],
        "duration": et["duration"],
        "locations": et.get("locations") or [],
    }


def _location_body(locations):
    """Build the 'location' object from the event type's configured location."""
    if not locations:
        return None
    loc = locations[0]
    kind = loc.get("kind")
    if not kind:
        return None
    body = {"kind": kind}
    for key in ("location", "phone_number"):  # needed for physical / call / custom kinds
        if loc.get(key):
            body[key] = loc[key]
    return body


def book_via_api(event_type_uri, start_utc, name, email, tz_name, locations=None):
    """Paid plans / trials only. Returns (ok, resource_or_error_text)."""
    body = {
        "event_type": event_type_uri,
        "start_time": start_utc,
        "invitee": {"name": name, "email": email, "timezone": tz_name},
    }
    loc = _location_body(locations)
    if loc:
        body["location"] = loc
    r = requests.post(f"{BASE}/invitees", headers=_headers(), json=body, timeout=20)
    if r.status_code in (200, 201):
        return True, r.json().get("resource", {})
    if r.status_code == 429:
        wait = r.headers.get("Retry-After") or r.headers.get("X-RateLimit-Reset")
        hint = f" Try again in about {wait} seconds." if wait else " Try again later."
        return False, "429 Calendly rate limit reached." + hint
    return False, f"{r.status_code}: {r.text[:300]}"