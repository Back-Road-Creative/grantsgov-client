"""ProPublica EIN lookup against a synthetic fixture. No network."""

import copy
import json
from pathlib import Path

import pytest

from grantsgov_client import propublica

ORG = json.loads(
    (Path(__file__).parent / "fixtures" / "propublica_org.json").read_text())


def _fetcher(payload=ORG):
    def fetch(path):
        return copy.deepcopy(payload)
    return fetch


def test_normalize_ein_keeps_nine_digits_and_nothing_else():
    assert propublica.normalize_ein("00-0000000") == "000000000"
    assert propublica.normalize_ein("000000000") == "000000000"
    assert propublica.normalize_ein("12345") is None
    assert propublica.normalize_ein("") is None
    assert propublica.normalize_ein(None) is None


def test_lookup_reduces_the_registry_record_to_a_prefill():
    prefill = propublica.lookup("000000000", fetcher=_fetcher())

    assert prefill == {
        "name": "Example Valley Food Alliance",
        "city": "Example City",
        "state": "OH",
        "ntee_code": "K30",
        "focus_area": "food_nutrition",   # seeded from the NTEE major group
        "annual_revenue": 320_000.0,
        "org_type": "nonprofit_501c3",    # subsection 3
        "capacity_band": "k100_500k",     # seeded from revenue
    }


def test_a_non_501c3_subsection_is_still_a_nonprofit():
    payload = copy.deepcopy(ORG)
    payload["organization"]["subsection_code"] = 12
    prefill = propublica.lookup("000000000", fetcher=_fetcher(payload))
    assert prefill["org_type"] == "nonprofit_other"


def test_an_unrecognised_state_is_dropped_rather_than_guessed():
    payload = copy.deepcopy(ORG)
    payload["organization"]["state"] = "ZZ"
    payload["organization"]["ntee_code"] = "  "
    prefill = propublica.lookup("000000000", fetcher=_fetcher(payload))
    assert prefill["state"] is None
    assert prefill["ntee_code"] is None and prefill["focus_area"] is None


def test_lookup_reports_an_offline_failure_rather_than_leaking_it():
    def boom(path):
        raise OSError("no network")

    with pytest.raises(propublica.LookupFailed) as caught:
        propublica.lookup("000000000", fetcher=boom)
    assert str(caught.value) == "lookup failed: OSError"


def test_lookup_rejects_a_response_with_no_organisation():
    with pytest.raises(propublica.LookupFailed):
        propublica.lookup("000000000", fetcher=_fetcher({"organization": None}))


def test_capacity_from_revenue_bands():
    assert propublica.capacity_from_revenue(10_000) == "under_25k"
    assert propublica.capacity_from_revenue(320_000) == "k100_500k"
    assert propublica.capacity_from_revenue(5_000_000) == "over_1m"
    assert propublica.capacity_from_revenue(None) is None
    assert propublica.capacity_from_revenue("not a number") is None


def test_diff_profile_reports_only_real_disagreement():
    stored = {"city": "Old Town", "state": "OH", "org_type": "nonprofit_501c3",
              "capacity_band": "k100_500k", "annual_revenue": 320_000,
              "ntee_code": "K30"}
    fresh = propublica.lookup("000000000", fetcher=_fetcher())

    assert propublica.diff_profile(stored, fresh) == [
        ("city", "Old Town", "Example City")]


def test_an_upstream_blank_never_proposes_erasing_a_stored_value():
    """A gap in the registry is a gap, not a correction."""
    stored = {"city": "Old Town", "ntee_code": "K30"}
    fresh = {"city": None, "ntee_code": ""}
    assert propublica.diff_profile(stored, fresh) == []


def test_diff_profile_ignores_fields_outside_the_refreshable_set():
    """The organisation's own name is never up for automatic replacement."""
    assert "name" not in propublica.REFRESHABLE_FIELDS
    stored = {"name": "The Name We Registered"}
    assert propublica.diff_profile(stored, {"name": "Something Scraped"}) == []


def test_scan_profiles_is_paced_and_survives_one_failure():
    """One bad EIN must not abort the pass, and the first call never waits."""
    calls, pauses = [], []

    def fetch(path):
        calls.append(path)
        if "111111111" in path:
            raise OSError("no network")
        return copy.deepcopy(ORG)

    stored = {"state": "OH", "org_type": "nonprofit_501c3",
              "capacity_band": "k100_500k", "annual_revenue": 320_000,
              "ntee_code": "K30"}
    rows = [{"ein": "000000000", "city": "Old Town", **stored},
            {"ein": "11-1111111", "city": "Elsewhere", **stored},
            {"ein": "not an ein", "city": "Skipped"},
            {"ein": None, "city": "Also skipped"}]

    results = list(propublica.scan_profiles(
        rows, fetcher=fetch, sleep=pauses.append))

    assert len(results) == 2                        # two rows had usable EINs
    assert len(calls) == 2
    assert pauses == [propublica.REQUEST_PAUSE]     # one gap between two calls
    assert results[0][1] == [("city", "Old Town", "Example City")]
    assert results[0][2] is None
    assert results[1][1] == [] and results[1][2] == "lookup failed: OSError"
