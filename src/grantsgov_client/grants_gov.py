"""Grants.gov connector: search sweep, per-id detail fetch, normalization.

The `search2` endpoint returns shallow hits (id, number, title, agency, dates,
status); the rich record (synopsis, eligibility, award amounts, deadline)
requires one `fetchOpportunity` call per opportunity. Both are public JSON
POST endpoints with no API key and no published numeric rate limit, so the
sweep paces itself as a matter of politeness.

Everything fetched is untrusted data: normalized to plain text, never
executed, never followed.
"""

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from . import vocabulary
from .text import plain_text

__all__ = [
    "API_BASE", "ConnectorError", "DATE_RANGE_BUCKETS", "HTTP_MAX_ATTEMPTS",
    "date_range_since", "fetch_detail", "http_fetch", "normalize_detail",
    "normalize_hit", "plain_text", "since_fetcher", "sweep",
]

API_BASE = "https://api.grants.gov/v1/api"

# A retry stays as polite as the sweep it sits inside: the first wait *is* the
# pacing pause and each later one doubles it, so a struggling upstream sees
# strictly less of us than a healthy one does.
HTTP_MAX_ATTEMPTS = 3  # one try plus two retries


class ConnectorError(Exception):
    """Upstream refused, or returned a malformed envelope."""


def _retriable(exc):
    """Retry the wire, never the request: a 4xx means we asked wrongly and
    repeating it is just hammering. A 200 whose body will not parse raises
    ValueError, which never reaches here - also not retried."""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500
    return True  # URLError, reset, DNS, socket timeout - transport, not us


def http_fetch(endpoint, payload, sleep=time.sleep,
               attempts=HTTP_MAX_ATTEMPTS, pause=vocabulary.REQUEST_PAUSE,
               timeout=30):
    """POST one JSON request, retrying transport faults with doubling backoff.

    The only place this module touches the network. `sleep` is injectable so a
    test suite never actually waits, and every other function here takes a
    `fetcher` callable so the whole library can run against recorded fixtures.
    """
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    req = urllib.request.Request(  # noqa: S310 - fixed https base, not caller-controlled
        f"{API_BASE}/{endpoint}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                return json.loads(resp.read().decode())
        except OSError as exc:  # HTTPError / URLError / timeout all subclass this
            if attempt == attempts - 1 or not _retriable(exc):
                raise
            sleep(pause * 2 ** attempt)
    raise AssertionError("unreachable: the loop returns or raises")  # pragma: no cover


# search2's only posted-date filter is `dateRange`: discrete "last N days"
# buckets, not an arbitrary since-date. It filters on *posted* date only - an
# edit to an already-posted opportunity does not come back through it - so a
# date-filtered sweep supplements a full one, it never replaces it.
DATE_RANGE_BUCKETS = (3, 7, 14, 21, 28, 35, 42, 49, 56)


def date_range_since(stamp, now=None):
    """Smallest bucket fully covering `stamp`..now, as a string, else None.

    None means "no bucket can cover this": never synced, an unparseable stamp,
    or a gap wider than the widest bucket. In every one of those cases the
    caller owes a full sweep rather than a narrower one.

    Always rounds up. A bucket shorter than the real gap silently skips
    whatever was posted in the days it left out.

    `stamp` is an ISO-8601 UTC instant, e.g. "2026-07-20T00:00:00Z".
    """
    try:
        seen = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return None
    gap = ((now or datetime.now(timezone.utc))
           - seen.replace(tzinfo=timezone.utc)).total_seconds() / 86_400
    return next((str(b) for b in DATE_RANGE_BUCKETS if b >= gap), None)


def since_fetcher(fetcher, date_range):
    """Wrap a fetcher so every search2 page carries `dateRange`.

    Detail fetches pass through untouched, and the caller's payload is copied
    rather than mutated.
    """
    def fetch(endpoint, payload):
        if endpoint == "search2":
            payload = {**payload, "dateRange": date_range}
        return fetcher(endpoint, payload)
    return fetch


def _envelope(data, endpoint):
    """Unwrap the {errorcode, msg, data} envelope both endpoints return.

    Raises `ConnectorError` for every way the response can fail to be one: an
    upstream error code, a body that is not a JSON object (list, string,
    null), or a success envelope whose `data` is missing or not an object.
    Callers never see an AttributeError or KeyError from a bad payload.
    """
    if not isinstance(data, dict):
        raise ConnectorError(
            f"{endpoint}: malformed response: expected a JSON object, "
            f"got {type(data).__name__}")
    if data.get("errorcode") != 0:
        raise ConnectorError(
            f"{endpoint}: upstream error "
            f"{data.get('errorcode')}: {data.get('msg')}")
    payload = data.get("data")
    if not isinstance(payload, dict):
        raise ConnectorError(
            f"{endpoint}: malformed response: 'data' is "
            f"{'missing' if 'data' not in data else type(payload).__name__}, "
            "expected a JSON object")
    return payload


def sweep(fetcher=http_fetch, sleep=time.sleep, statuses="posted|forecasted",
          rows=vocabulary.PAGE_ROWS, pause=vocabulary.REQUEST_PAUSE,
          keyword=""):
    """Yield every shallow search2 hit for `statuses`, across all pages.

    `statuses` is the pipe-separated form Grants.gov expects. The generator
    pauses between pages, so a caller that stops early stops the requests too.
    """
    start = 0
    while True:
        data = _envelope(fetcher("search2", {
            "rows": rows, "startRecordNum": start,
            "oppStatuses": statuses, "keyword": keyword}), "search2")
        hits = data.get("oppHits") or []
        yield from hits
        start += len(hits)
        if not hits or start >= data.get("hitCount", 0):
            return
        sleep(pause)


def fetch_detail(fetcher, record_id):
    """The rich `fetchOpportunity` record for one opportunity id.

    `fetcher` is first for symmetry with `sweep` and `since_fetcher`; pass
    `http_fetch` to go to the network.
    """
    return _envelope(fetcher("fetchOpportunity",
                             {"opportunityId": int(record_id)}),
                     "fetchOpportunity")


def _date_mdy(value):
    """'06/22/2026' -> '2026-06-22' (None if absent or malformed)."""
    try:
        return datetime.strptime(value.strip(), "%m/%d/%Y").date().isoformat()
    except (AttributeError, ValueError):
        return None


def _date_verbose(value):
    """'Aug 03, 2026 12:00:00 AM EDT' -> '2026-08-03'."""
    try:
        stamp = " ".join(value.strip().split()[:3])  # drop time + zone
        return datetime.strptime(stamp, "%b %d, %Y").date().isoformat()
    except (AttributeError, ValueError):
        return None


def normalize_hit(hit):
    """One shallow search2 hit -> a flat dict, or None to quarantine it.

    None means the hit is unusable - no id, no title, or a status outside the
    published vocabulary. Returning it rather than raising lets one bad row be
    set aside without aborting a sweep of thousands.
    """
    record_id = str(hit.get("id") or "").strip()
    title = plain_text(hit.get("title"), cap=500)
    status = hit.get("oppStatus")
    if not record_id or not title or status not in vocabulary.OPPORTUNITY_STATUSES:
        return None
    return {
        "source_record_id": record_id,
        "opp_number": plain_text(hit.get("number"), cap=80),
        "title": title,
        "funder_name": plain_text(hit.get("agency"), cap=200) or "Unknown",
        "open_date": _date_mdy(hit.get("openDate")),
        "close_date": _date_mdy(hit.get("closeDate")),
        "status": status,
        "raw_url": "https://www.grants.gov/search-results-detail/" + record_id,
    }


def normalize_detail(detail):
    """A fetchOpportunity payload -> (fields, eligible_org_types).

    `fields` carries only what the payload actually stated, so merging it over
    a normalized hit never overwrites a known value with a blank. A forecast
    record is read the same way as a posted synopsis.

    `eligible_org_types` is a sorted list of this library's org-type keys.
    Applicant code "99" (unrestricted) expands to every key.
    """
    syn = detail.get("synopsis") or detail.get("forecast") or {}
    fields = {}
    text = plain_text(syn.get("synopsisDesc"))
    if text:
        fields["synopsis"] = text
    for key, source in (("amount_floor", "awardFloor"),
                        ("amount_ceiling", "awardCeiling")):
        try:
            fields[key] = float(syn[source])
        except (KeyError, TypeError, ValueError):
            pass
    deadline = _date_verbose(syn.get("responseDate"))
    if deadline:
        fields["close_date"] = deadline
    categories = syn.get("fundingActivityCategories") or []
    if categories:
        fields["category"] = vocabulary.GRANTS_GOV_CATEGORY_MAP.get(
            categories[0].get("id"), "other")
    org_types = set()
    for entry in syn.get("applicantTypes") or []:
        code = str(entry.get("id", ""))
        if code == vocabulary.UNRESTRICTED_APPLICANT_CODE:
            org_types.update(vocabulary.ORG_TYPE_KEYS)
        elif code in vocabulary.GRANTS_GOV_APPLICANT_MAP:
            org_types.add(vocabulary.GRANTS_GOV_APPLICANT_MAP[code])
    return fields, sorted(org_types)
