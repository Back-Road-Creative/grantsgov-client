"""ProPublica Nonprofit Explorer connector: EIN lookup for profile prefill.

Public JSON GET, no API key. One request returns the IRS registration record
for an EIN; this module reduces it to the handful of fields an organisation
profile actually wants, normalized and length-capped.

The lookup is an explicit online action - there is no background polling here.
Everything fetched is untrusted data: plain-text normalized, never executed,
never followed.
"""

import json
import re
import time
import urllib.request

from . import vocabulary
from .text import plain_text

__all__ = [
    "API_BASE", "LookupFailed", "REFRESHABLE_FIELDS", "REQUEST_PAUSE",
    "capacity_from_revenue", "diff_profile", "http_fetch", "lookup",
    "normalize_ein", "scan_profiles",
]

API_BASE = "https://projects.propublica.org/nonprofits/api/v2"

# Keyless, with no published numeric rate limit, so a bulk pass paces itself
# the same way the Grants.gov sweep does: roughly one request a second.
REQUEST_PAUSE = vocabulary.REQUEST_PAUSE

# The profile fields a registry lookup is allowed to propose a change to.
# The organisation's own name and any hand-written prose are deliberately
# absent: a scrape must never be able to overwrite either.
REFRESHABLE_FIELDS = ("org_type", "city", "state", "capacity_band",
                      "annual_revenue", "ntee_code")


class LookupFailed(Exception):
    """Upstream unreachable, or no organisation for that EIN."""


def http_fetch(path, timeout=20):
    """GET one JSON path under the API base. The only network call here."""
    with urllib.request.urlopen(f"{API_BASE}/{path}", timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode())


def normalize_ein(raw):
    """'00-1234567' or '001234567' -> '001234567'; None if not nine digits."""
    digits = re.sub(r"\D", "", raw or "")
    return digits if len(digits) == 9 else None


def lookup(ein, fetcher=None):
    """EIN -> a profile-prefill dict.

    Keys: name, city, state, ntee_code, focus_area, annual_revenue, org_type,
    capacity_band. Any of them may be None when the registry is silent.

    Raises LookupFailed when the request fails or the response carries no
    organisation - the caller's fallback is manual entry.
    """
    fetcher = fetcher or http_fetch
    try:
        payload = fetcher(f"organizations/{ein}.json")
    except Exception as exc:
        raise LookupFailed(f"lookup failed: {type(exc).__name__}") from exc
    org = (payload or {}).get("organization") or {}
    if not org:
        raise LookupFailed("no organization in response")
    ntee = (org.get("ntee_code") or "").strip().upper() or None
    focus = vocabulary.NTEE_FOCUS_MAP.get(ntee[0]) if ntee else None
    state = (org.get("state") or "").strip().upper()
    revenue = org.get("revenue_amount") or org.get("income_amount")
    return {
        "name": plain_text(org.get("name"), cap=120),
        "city": plain_text(org.get("city"), cap=80),
        "state": state if state in vocabulary.GEOGRAPHIES else None,
        "ntee_code": ntee,
        "focus_area": focus,
        "annual_revenue": float(revenue) if revenue is not None else None,
        # Subsection 3 is the 501(c)(3) exemption; the registry has spelled it
        # as an int and as a zero-padded string, under two different key names.
        "org_type": ("nonprofit_501c3"
                     if org.get("subsection_code") in (3, "03", "3")
                     or org.get("subseccd") in (3, "03", "3")
                     else "nonprofit_other"),
        "capacity_band": capacity_from_revenue(revenue),
    }


def capacity_from_revenue(revenue):
    """Seed an amount band from annual revenue. A default, not a verdict."""
    try:
        revenue = float(revenue)
    except (TypeError, ValueError):
        return None
    for key, (lo, hi) in vocabulary.AMOUNT_BAND_RANGE.items():
        if revenue >= lo and (hi is None or revenue < hi):
            return key
    return None


def _comparable(field, value):
    """Normalize one field for a stored-vs-upstream comparison."""
    if field == "annual_revenue":
        try:
            return round(float(value), 2)
        except (TypeError, ValueError):
            return None
    return (value or "").strip() or None


def diff_profile(stored, fresh):
    """[(field, stored_value, upstream_value)] where the registry disagrees.

    An upstream blank is never a difference: a gap in the registry must not
    propose erasing a value the operator holds. Fields outside
    REFRESHABLE_FIELDS are not looked at.

    `stored` is any mapping-like row exposing `.keys()` - a dict or a
    `sqlite3.Row` both work.
    """
    drift = []
    stored_keys = set(stored.keys())
    for field in REFRESHABLE_FIELDS:
        upstream = fresh.get(field)
        if _comparable(field, upstream) is None:
            continue
        old = stored[field] if field in stored_keys else None
        if _comparable(field, old) != _comparable(field, upstream):
            drift.append((field, old, upstream))
    return drift


def scan_profiles(rows, fetcher=None, sleep=time.sleep, pause=REQUEST_PAUSE):
    """Yield (row, drift, error) for every row that carries a usable EIN.

    Read-only and resilient: one row's failed lookup yields an error string
    and the scan moves on, so a single bad EIN cannot abort the pass. Rows
    whose `ein` is missing or malformed are skipped silently - they have
    nothing to look up.

    Requests are paced by `pause` seconds, and the first request never waits.
    `fetcher` and `sleep` are injectable so a suite can run offline.
    """
    calls = 0
    for row in rows:
        ein = normalize_ein(row["ein"])
        if ein is None:
            continue
        if calls:
            sleep(pause)
        calls += 1
        try:
            fresh = lookup(ein, fetcher=fetcher)
        except LookupFailed as exc:
            yield row, [], str(exc)
            continue
        yield row, diff_profile(row, fresh), None
