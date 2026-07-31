"""Fit scoring: golden numbers, the reasons-sum-to-the-score invariant,
determinism, the injected clock, and re-wordable reason templates."""

from datetime import date, timedelta

import pytest

from grantsgov_client import matching
from grantsgov_client.matching import WEIGHTS, Reason, rank, score

TODAY = date(2026, 3, 1)

# Synthetic. No real organisation's profile appears in this suite.
PROFILE = {"org_type": "nonprofit_501c3", "state": "OH",
           "geographies": ["OH"], "focus_areas": ["food_nutrition"],
           "capacity_band": "k25_100k"}

ELIGIBLE = {"nonprofit_501c3"}


def opp(**over):
    """A perfect match for PROFILE, so each test varies exactly one thing."""
    fields = {"id": 1, "geography": "OH", "category": "food_nutrition",
              "amount_floor": 10_000, "amount_ceiling": 60_000,
              "close_date": (TODAY + timedelta(days=45)).isoformat()}
    fields.update(over)
    return fields


def points(profile=PROFILE, eligible=ELIGIBLE, **over):
    return score(profile, opp(**over), eligible, today=TODAY)[0]


# --- the invariant -----------------------------------------------------------


def test_the_weights_are_a_hundred_point_scale():
    assert sum(WEIGHTS.values()) == 100


def test_every_point_is_accounted_for_by_a_reason():
    """The whole promise of the scorer: sum the reasons, get the score back,
    with exactly one reason per dimension and no orphan points."""
    for eligible in (ELIGIBLE, {"tribal"}, set()):
        for geography in ("OH", "US", "CA"):
            total, reasons = score(PROFILE, opp(geography=geography),
                                   eligible, today=TODAY)
            assert sum(r.points for r in reasons) == total
            assert [r.dimension for r in reasons] == list(WEIGHTS)


def test_a_perfect_state_match_scores_a_hundred():
    total, reasons = score(PROFILE, opp(), ELIGIBLE, today=TODAY)
    assert total == 100
    assert [r.text for r in reasons] == [
        "Eligible organization type: Nonprofit (501(c)(3))",
        "Serves OH",
        "Focus area matches: Food & Nutrition",
        "Award size fits the capacity band",
        "45 days to prepare",
    ]


def test_score_is_deterministic():
    assert {points() for _ in range(5)} == {100}


# --- dimension by dimension --------------------------------------------------


def test_a_national_opportunity_scores_just_under_a_state_one():
    assert points() - points(geography="US") == matching.NATIONAL_DISCOUNT


def test_a_stated_mismatch_scores_nothing_on_its_axis():
    assert points() - points(eligible={"tribal"}) == WEIGHTS["org_type"]
    assert points() - points(category="transportation") == WEIGHTS["focus"]
    assert (points() - points(amount_floor=2_000_000,
                              amount_ceiling=5_000_000) == WEIGHTS["amount"])


@pytest.mark.parametrize("dimension, kwargs, ceiling", [
    # Unstated eligibility on the listing, and an unstated org type on the
    # profile, both earn the same partial credit: neither is a "no".
    ("org_type", {"eligible": set()}, WEIGHTS["org_type"]),
    ("org_type", {"profile": {**PROFILE, "org_type": None}},
     WEIGHTS["org_type"]),
    ("geography", {"geography": None}, WEIGHTS["geography"]),
    ("geography", {"geography": "CA",
                   "profile": {k: v for k, v in PROFILE.items()
                               if k not in ("state", "geographies")}},
     WEIGHTS["geography"]),
    ("focus", {"category": "other"}, WEIGHTS["focus"]),
    ("focus", {"profile": {**PROFILE, "focus_areas": []}}, WEIGHTS["focus"]),
    ("amount", {"profile": {**PROFILE, "capacity_band": None}},
     WEIGHTS["amount"]),
    ("amount", {"amount_floor": None, "amount_ceiling": None},
     WEIGHTS["amount"]),
    ("deadline", {"close_date": None}, WEIGHTS["deadline"]),
])
def test_unknown_is_not_a_no(dimension, kwargs, ceiling):
    """Silence earns partial credit on every dimension - more than a stated
    mismatch, less than a stated match."""
    unknown = points(**kwargs)
    assert 0 < points() - unknown < ceiling


def test_the_deadline_is_a_gradient_not_a_cliff():
    ample = points()
    tight = points(close_date=(TODAY + timedelta(days=10)).isoformat())
    urgent = points(close_date=(TODAY + timedelta(days=2)).isoformat())
    passed = points(close_date=(TODAY - timedelta(days=1)).isoformat())
    assert ample > tight > urgent == passed


def test_an_open_ended_award_ceiling_still_overlaps_a_band():
    """A floor inside the band and no ceiling at all is a fit, not a miss."""
    total, reasons = score(PROFILE, opp(amount_ceiling=None), ELIGIBLE,
                           today=TODAY)
    assert next(r for r in reasons if r.dimension == "amount").code == "match"


def test_an_unknown_label_falls_back_to_its_key():
    """A vocabulary this library has not seen must not crash the scorer."""
    total, reasons = score({**PROFILE, "focus_areas": ["quantum_basketry"]},
                           opp(category="quantum_basketry"), ELIGIBLE,
                           today=TODAY)
    assert "quantum_basketry" in str(reasons[2])


# --- the clock seam ----------------------------------------------------------


def test_the_clock_is_injectable():
    """Same opportunity, two different 'todays', two different deadline
    verdicts - no hidden call to the system clock."""
    deadline = opp(close_date="2026-03-20")
    early = score(PROFILE, deadline, ELIGIBLE, today=date(2026, 3, 1))
    late = score(PROFILE, deadline, ELIGIBLE, today=date(2026, 3, 21))
    assert early[0] > late[0]
    assert early[1][-1].code == "ample" and late[1][-1].code == "passed"


def test_omitting_the_clock_uses_today():
    live = score(PROFILE, opp(close_date=(date.today() +
                                          timedelta(days=45)).isoformat()),
                 ELIGIBLE)
    assert live[1][-1].code == "ample"


# --- reason wording ----------------------------------------------------------


def test_reasons_carry_structure_as_well_as_words():
    _, reasons = score(PROFILE, opp(), ELIGIBLE, today=TODAY)
    first = reasons[0]
    assert isinstance(first, Reason)
    assert first.key == "org_type.match"
    assert first.points == WEIGHTS["org_type"]
    assert str(first) == first.text


def test_templates_can_be_re_worded_without_touching_the_arithmetic():
    plain = score(PROFILE, opp(), ELIGIBLE, today=TODAY)
    rewritten = score(PROFILE, opp(), ELIGIBLE, today=TODAY,
                      templates={"geography.match": "Deckt {geography} ab"})
    assert rewritten[0] == plain[0]
    assert rewritten[1][1].text == "Deckt OH ab"
    assert matching.REASON_TEMPLATES["geography.match"] == "Serves {geography}"


def test_every_template_key_is_reachable_and_every_branch_has_one():
    """No dead template, and no branch rendering a KeyError instead of a
    sentence. Walks every code the scorer can emit."""
    cases = [
        ({}, {"eligible": set()}),
        ({}, {}),
        ({"org_type": None}, {}),
        ({"org_type": "tribal"}, {}),
        ({}, {"geography": None}),
        ({}, {"geography": "US"}),
        ({}, {"geography": "OH"}),
        ({"state": None, "geographies": []}, {"geography": "CA"}),
        ({}, {"geography": "CA"}),
        ({}, {"category": "other"}),
        ({}, {"category": "transportation"}),
        ({"capacity_band": None}, {}),
        ({}, {"amount_floor": 2_000_000, "amount_ceiling": 5_000_000}),
        ({}, {"close_date": None}),
        ({}, {"close_date": (TODAY + timedelta(days=10)).isoformat()}),
        ({}, {"close_date": (TODAY + timedelta(days=2)).isoformat()}),
        ({}, {"close_date": (TODAY - timedelta(days=1)).isoformat()}),
    ]
    seen = set()
    for profile_over, opp_over in cases:
        eligible = opp_over.pop("eligible", ELIGIBLE)
        _, reasons = score({**PROFILE, **profile_over}, opp(**opp_over),
                           eligible, today=TODAY)
        seen.update(r.key for r in reasons)
    assert seen == set(matching.REASON_TEMPLATES)


# --- ranking -----------------------------------------------------------------


SOON = opp(id=1, close_date=(TODAY + timedelta(days=40)).isoformat())
LATER = opp(id=4, close_date=(TODAY + timedelta(days=80)).isoformat())
UNDATED = opp(id=3, close_date=None)
OFF_TOPIC = opp(id=2, geography="US", category="transportation",
                close_date=(TODAY + timedelta(days=40)).isoformat())

CATALOG = [OFF_TOPIC, UNDATED, LATER, SOON]
ELIGIBILITY = {1: {"nonprofit_501c3"}, 2: {"government_local"},
               3: {"nonprofit_501c3"}, 4: {"nonprofit_501c3"}}


def test_rank_orders_by_score_then_soonest_deadline_then_id():
    ranked = rank(PROFILE, CATALOG, ELIGIBILITY, today=TODAY)

    assert [m["opp"]["id"] for m in ranked] == [1, 4, 3, 2]
    # 1 and 4 tie on score; the sooner deadline wins. 3 has no deadline, so it
    # sorts after both of them rather than before.
    assert ranked[0]["score"] == ranked[1]["score"]
    assert ranked[0]["score"] > ranked[-1]["score"]


def test_rank_is_stable_across_input_order():
    forward = rank(PROFILE, CATALOG, ELIGIBILITY, today=TODAY)
    backward = rank(PROFILE, list(reversed(CATALOG)), ELIGIBILITY, today=TODAY)
    assert [m["opp"]["id"] for m in forward] == \
           [m["opp"]["id"] for m in backward]


def test_rank_applies_the_minimum_score_filter():
    ranked = rank(PROFILE, CATALOG, ELIGIBILITY, min_score=100, today=TODAY)
    assert [m["opp"]["id"] for m in ranked] == [1, 4]


def test_rank_treats_an_unlisted_opportunity_as_eligibility_unstated():
    ranked = rank(PROFILE, [SOON], {}, today=TODAY)
    assert ranked[0]["reasons"][0].code == "unstated"
