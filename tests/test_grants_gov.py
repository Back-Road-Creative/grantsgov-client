"""Grants.gov connector, driven entirely from recorded fixtures. No network."""

import copy
import io
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pytest

from grantsgov_client import grants_gov, vocabulary
from grantsgov_client.text import plain_text

FIXTURES = Path(__file__).parent / "fixtures"
SEARCH2 = json.loads((FIXTURES / "search2_posted.json").read_text())
DETAIL = json.loads((FIXTURES / "fetch_opportunity.json").read_text())


def make_fetcher(search_response=SEARCH2):
    """A fetcher that pages the recorded hits the way search2 really does."""
    calls = {"search2": 0, "fetchOpportunity": 0}

    def fetch(endpoint, payload):
        calls[endpoint] += 1
        if endpoint == "search2":
            page = copy.deepcopy(search_response)
            start = payload.get("startRecordNum", 0)
            hits = page["data"].get("oppHits") or []
            page["data"]["oppHits"] = hits[start:start + payload["rows"]]
            page["data"]["hitCount"] = len(hits)
            return page
        return copy.deepcopy(DETAIL)

    fetch.calls = calls
    return fetch


# --- transport ---------------------------------------------------------------


def _script_urlopen(monkeypatch, outcomes):
    """urlopen walks `outcomes`: raise an exception, or return bytes."""
    calls = []

    def fake(request, timeout=None):
        calls.append(request.full_url)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return io.BytesIO(outcome)  # BytesIO is already a context manager

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return calls


def test_http_fetch_retries_transport_faults_and_stays_polite(monkeypatch):
    """A reset, then a 5xx, then success: one fetch, three attempts, and no
    wait shorter than the politeness pause. Backoff extends the pacing; it
    never undercuts it into a hammer."""
    waits = []
    calls = _script_urlopen(monkeypatch, [
        urllib.error.URLError("connection reset"),
        urllib.error.HTTPError("http://x", 503, "unavailable", None, None),
        b'{"errorcode": 0, "data": {"ok": true}}'])

    data = grants_gov.http_fetch("search2", {"rows": 1}, sleep=waits.append)

    assert data["data"]["ok"] is True
    assert len(calls) == 3
    assert waits == [vocabulary.REQUEST_PAUSE, vocabulary.REQUEST_PAUSE * 2]


def test_http_fetch_refuses_a_4xx_on_the_first_attempt(monkeypatch):
    """A 4xx is our request being wrong. Repeating it is pure hammering."""
    waits = []
    calls = _script_urlopen(monkeypatch, [
        urllib.error.HTTPError("http://x", 400, "bad request", None, None)])

    with pytest.raises(urllib.error.HTTPError):
        grants_gov.http_fetch("search2", {"rows": 1}, sleep=waits.append)

    assert len(calls) == 1 and waits == []


def test_http_fetch_caps_transport_retries(monkeypatch):
    waits = []
    calls = _script_urlopen(monkeypatch, [urllib.error.URLError("down")] * 9)

    with pytest.raises(urllib.error.URLError):
        grants_gov.http_fetch("search2", {"rows": 1}, sleep=waits.append)

    assert len(calls) == grants_gov.HTTP_MAX_ATTEMPTS
    assert len(waits) == grants_gov.HTTP_MAX_ATTEMPTS - 1  # none after the last


def test_http_fetch_rejects_a_nonsense_attempt_count():
    with pytest.raises(ValueError):
        grants_gov.http_fetch("search2", {}, attempts=0)


# --- sweep -------------------------------------------------------------------


def test_sweep_pages_through_every_hit_and_paces_itself():
    fetcher, waits = make_fetcher(), []
    hits = list(grants_gov.sweep(fetcher, sleep=waits.append, rows=2))

    assert [h["id"] for h in hits] == ["361403", "355044", "363119",
                                       "320536", "359816"]
    assert fetcher.calls["search2"] == 3  # 2 + 2 + 1
    # One pause between pages, none after the last.
    assert waits == [vocabulary.REQUEST_PAUSE] * 2


def test_sweep_stops_on_an_empty_page():
    empty = copy.deepcopy(SEARCH2)
    empty["data"]["oppHits"] = []
    fetcher = make_fetcher(empty)

    assert list(grants_gov.sweep(fetcher, sleep=lambda _s: None)) == []
    assert fetcher.calls["search2"] == 1


def test_an_upstream_error_envelope_raises():
    def fetch(endpoint, payload):
        return {"errorcode": 1, "msg": "Webservice Failed", "data": None}

    with pytest.raises(grants_gov.ConnectorError) as caught:
        list(grants_gov.sweep(fetch, sleep=lambda _s: None))
    assert "Webservice Failed" in str(caught.value)


def test_fetch_detail_unwraps_the_envelope():
    detail = grants_gov.fetch_detail(make_fetcher(), "361403")
    assert detail["opportunityNumber"] == "HHS-2026-ACL-AOD-DFLA-0025"


# --- date-range filtering ----------------------------------------------------


def test_date_range_rounds_up_and_refuses_an_uncoverable_gap():
    """Rounding down would silently skip whatever was posted in the days the
    shorter bucket left out, so every answer covers at least the real gap."""
    now = datetime(2026, 7, 21, tzinfo=timezone.utc)

    assert grants_gov.date_range_since("2026-07-20T00:00:00Z", now) == "3"
    assert grants_gov.date_range_since("2026-07-07T00:00:00Z", now) == "14"
    assert grants_gov.date_range_since(None, now) is None       # never fetched
    assert grants_gov.date_range_since("garbage", now) is None
    assert grants_gov.date_range_since("2026-01-01T00:00:00Z", now) is None


def test_date_range_buckets_match_the_recorded_options():
    """The buckets are upstream's, not ours - pin them to the recording."""
    recorded = tuple(int(o["value"])
                     for o in SEARCH2["data"]["dateRangeOptions"])
    assert grants_gov.DATE_RANGE_BUCKETS == recorded


def test_since_fetcher_tags_search_pages_only_and_copies_the_payload():
    seen = []

    def inner(endpoint, payload):
        seen.append((endpoint, payload))
        return {"errorcode": 0, "data": {}}

    payload = {"rows": 5}
    wrapped = grants_gov.since_fetcher(inner, "7")
    wrapped("search2", payload)
    wrapped("fetchOpportunity", {"opportunityId": 1})

    assert seen[0][1]["dateRange"] == "7"
    assert "dateRange" not in seen[1][1]
    assert payload == {"rows": 5}  # the caller's dict was never mutated


# --- normalization -----------------------------------------------------------


def _hit(index):
    return copy.deepcopy(SEARCH2["data"]["oppHits"][index])


def test_normalize_hit_flattens_a_shallow_record():
    row = grants_gov.normalize_hit(_hit(0))

    assert row == {
        "source_record_id": "361403",
        "opp_number": "HHS-2026-ACL-AOD-DFLA-0025",
        "title": ("Expanding Financial Literacy and Empowerment: Increasing"
                  " Awareness and Use of ABLE Accounts for Americans with"
                  " Disabilities"),
        "funder_name": "Administration for Community Living",
        "open_date": "2026-06-22",
        "close_date": "2026-08-03",
        "status": "posted",
        "raw_url": "https://www.grants.gov/search-results-detail/361403",
    }


def test_normalize_hit_unescapes_upstream_entities():
    assert "&ndash;" not in grants_gov.normalize_hit(_hit(2))["title"]


def test_normalize_hit_reads_a_blank_close_date_as_no_deadline():
    assert grants_gov.normalize_hit(_hit(3))["close_date"] is None


@pytest.mark.parametrize("break_it", [
    {"id": ""},
    {"title": ""},
    {"oppStatus": "something-upstream-invented"},
])
def test_normalize_hit_quarantines_an_unusable_record(break_it):
    """None, not an exception: one bad row is set aside, the sweep goes on."""
    hit = _hit(0)
    hit.update(break_it)
    assert grants_gov.normalize_hit(hit) is None


def test_normalize_hit_falls_back_to_an_unknown_funder():
    hit = _hit(0)
    hit["agency"] = ""
    assert grants_gov.normalize_hit(hit)["funder_name"] == "Unknown"


def test_normalize_detail_reads_the_rich_record():
    fields, org_types = grants_gov.normalize_detail(DETAIL["data"])

    assert fields["amount_floor"] == 1_000_000
    assert fields["amount_ceiling"] == 1_200_000
    assert fields["close_date"] == "2026-08-03"     # from the verbose form
    assert fields["category"] == "social_services"  # ISS -> our focus key
    assert fields["synopsis"].startswith("This grant is funded under")
    assert "<" not in fields["synopsis"]
    assert org_types == ["government_local", "government_state", "higher_ed",
                         "housing_authority", "nonprofit_501c3",
                         "nonprofit_other", "school_district", "tribal"]


def test_normalize_detail_states_nothing_it_was_not_told():
    """Absent keys stay absent, so merging over a shallow hit can never
    overwrite a known value with a blank."""
    fields, org_types = grants_gov.normalize_detail({"synopsis": {}})
    assert fields == {} and org_types == []


def test_normalize_detail_falls_back_to_a_forecast_record():
    """A forecast has no synopsis; its award floor arrives as a string."""
    fields, _ = grants_gov.normalize_detail(
        {"synopsis": None, "forecast": DETAIL["data"]["forecast"]})
    assert fields["amount_floor"] == 1_000_000
    assert fields["amount_ceiling"] == 1_500_000


def test_unrestricted_applicant_code_expands_to_every_org_type():
    _, org_types = grants_gov.normalize_detail(
        {"synopsis": {"applicantTypes": [{"id": "99"}]}})
    assert org_types == sorted(vocabulary.ORG_TYPE_KEYS)


def test_an_unknown_applicant_or_category_code_is_not_invented():
    fields, org_types = grants_gov.normalize_detail({"synopsis": {
        "applicantTypes": [{"id": "not-a-code"}],
        "fundingActivityCategories": [{"id": "not-a-code"}]}})
    assert org_types == []
    assert fields["category"] == "other"


# --- untrusted text ----------------------------------------------------------


def test_plain_text_strips_markup_collapses_space_and_caps_length():
    assert plain_text("<b>Ada</b>  &amp;\n Grace") == "Ada & Grace"
    assert plain_text("<script>x</script>") == "x"  # neutralised, not executed
    assert plain_text("abcdef", cap=3) == "abc"
    assert plain_text("") is None
    assert plain_text(None) is None
    assert plain_text("   ") is None  # collapses to nothing -> absent
