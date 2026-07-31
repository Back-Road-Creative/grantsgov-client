"""Explainable fit scoring: deterministic, and every point is traceable.

`score(profile, opportunity, eligible_org_types)` returns `(0..100, reasons)`.
Five weighted dimensions, fixed weights, no randomness and no model - the same
two inputs always produce the same number and the same reasons, so a ranked
list can always say *why*.

Two principles the weights encode:

* **Unknown is not a no.** A silent record earns partial credit, never zero.
  An opportunity that does not state its eligibility is a maybe; an
  organisation that has not filled in its focus areas is a maybe. Only a
  stated mismatch scores nothing.
* **Every point has a reason.** Each dimension appends exactly one `Reason`,
  carrying the points it contributed and a sentence you can show a human.
  Sum the reasons and you get the score back.

Reason wording is templated (`REASON_TEMPLATES`); pass your own `templates`
mapping to re-word or translate any line without touching the arithmetic.
"""

from dataclasses import dataclass
from datetime import date

from . import vocabulary

__all__ = [
    "MIN_PREP_DAYS", "REASON_TEMPLATES", "Reason", "TIGHT_PREP_DAYS",
    "WEIGHTS", "rank", "score",
]

WEIGHTS = {"org_type": 30, "geography": 25, "focus": 25, "amount": 10,
           "deadline": 10}

MIN_PREP_DAYS = 14   # a deadline closer than this is barely feasible
TIGHT_PREP_DAYS = 7  # ...and closer than this scores nothing

# A national opportunity is a real match, just a weaker signal than a program
# written for the applicant's own state - so it scores just under a state hit.
NATIONAL_DISCOUNT = 5


@dataclass(frozen=True)
class Reason:
    """One dimension's contribution, in points and in words."""

    dimension: str  # "org_type" | "geography" | "focus" | "amount" | "deadline"
    code: str       # which branch fired, e.g. "match", "unstated", "miss"
    points: int     # what this dimension added to the total
    text: str       # the rendered, human-readable sentence

    @property
    def key(self):
        """The `REASON_TEMPLATES` key this reason was rendered from."""
        return f"{self.dimension}.{self.code}"

    def __str__(self):
        return self.text


REASON_TEMPLATES = {
    # org_type
    "org_type.unstated": "Eligibility is not stated - check the source listing",
    "org_type.match": "Eligible organization type: {label}",
    "org_type.unknown": "Add an organization type to confirm eligibility",
    "org_type.miss": "Organization type is not in the eligible list",
    # geography
    "geography.national": "National opportunity",
    "geography.match": "Serves {geography}",
    "geography.unstated": "No geography stated on the opportunity",
    "geography.unknown": "Add the geographies served to match state programs",
    "geography.miss": "Outside the geographies served ({geography})",
    # focus
    "focus.match": "Focus area matches: {label}",
    "focus.unknown": "Focus area match unknown",
    "focus.miss": "Outside the stated focus areas ({label})",
    # amount
    "amount.match": "Award size fits the capacity band",
    "amount.miss": "Award size is outside the capacity band",
    "amount.unknown": "Award size fit unknown",
    # deadline
    "deadline.none": "No deadline posted",
    "deadline.ample": "{days} days to prepare",
    "deadline.tight": "Tight deadline ({days} days)",
    "deadline.urgent": "Deadline in {days} day(s) - barely feasible",
    "deadline.passed": "Deadline has passed",
}


def _label(key, labels):
    """A display label for a canonical key, falling back to the key itself."""
    if key is None:
        return "unspecified"
    return labels.get(key, key)


def score(profile, opp, eligible_org_types, today=None, templates=None,
          labels=None):
    """Score one organisation profile against one opportunity.

    Returns `(total, reasons)` - an int in 0..100 and a list of `Reason`,
    one per dimension, whose `points` sum to `total`.

    `profile` reads these optional keys: `org_type`, `state`, `geographies`
    (iterable of geography codes), `focus_areas` (iterable of focus keys),
    `capacity_band` (an amount-band key). Anything absent is treated as
    unknown, not as a mismatch.

    `opp` reads: `geography` (a state code or "US"), `category` (a focus key),
    `amount_floor`, `amount_ceiling`, `close_date` (an ISO date string, or
    None for "no deadline posted").

    `eligible_org_types` is the container returned by
    `grants_gov.normalize_detail`; empty means the listing did not say.

    `today` is the clock seam - pass a `datetime.date` to make deadline
    scoring reproducible. `templates` and `labels` override the wording only;
    neither can change the arithmetic.
    """
    today = today or date.today()
    templates = {**REASON_TEMPLATES, **(templates or {})}
    labels = labels if labels is not None else vocabulary.LABELS
    total, reasons = 0, []

    def add(dimension, code, points, **fields):
        nonlocal total
        total += points
        reasons.append(Reason(
            dimension, code, points,
            templates[f"{dimension}.{code}"].format(**fields)))

    # --- Organization type (eligibility) ---
    org_type = profile.get("org_type")
    if not eligible_org_types:
        add("org_type", "unstated", WEIGHTS["org_type"] // 3)
    elif org_type in eligible_org_types:
        add("org_type", "match", WEIGHTS["org_type"],
            label=_label(org_type, labels))
    elif not org_type:
        add("org_type", "unknown", WEIGHTS["org_type"] // 3)
    else:
        add("org_type", "miss", 0, label=_label(org_type, labels))

    # --- Geography ---
    geography = opp.get("geography")
    served = set(profile.get("geographies") or ())
    home = profile.get("state")
    if geography == vocabulary.NATIONAL:
        add("geography", "national", WEIGHTS["geography"] - NATIONAL_DISCOUNT)
    elif geography and (geography in served or geography == home):
        add("geography", "match", WEIGHTS["geography"], geography=geography)
    elif not geography:
        add("geography", "unstated", WEIGHTS["geography"] // 5)
    elif not served and not home:
        add("geography", "unknown", WEIGHTS["geography"] // 5)
    else:
        add("geography", "miss", 0, geography=geography)

    # --- Focus area ---
    category = opp.get("category")
    focus = set(profile.get("focus_areas") or ())
    if category and category in focus:
        add("focus", "match", WEIGHTS["focus"], label=_label(category, labels))
    elif not category or category == "other" or not focus:
        add("focus", "unknown", WEIGHTS["focus"] // 5)
    else:
        add("focus", "miss", 0, label=_label(category, labels))

    # --- Award size vs. capacity ---
    band = profile.get("capacity_band")
    floor, ceiling = opp.get("amount_floor"), opp.get("amount_ceiling")
    band_range = vocabulary.AMOUNT_BAND_RANGE.get(band) if band else None
    if band_range and (floor is not None or ceiling is not None):
        lo, hi = band_range
        overlap = ((ceiling is None or ceiling >= lo)
                   and (hi is None or floor is None or floor <= hi))
        add("amount", "match" if overlap else "miss",
            WEIGHTS["amount"] if overlap else 0)
    else:
        add("amount", "unknown", WEIGHTS["amount"] // 2)

    # --- Deadline ---
    close = opp.get("close_date")
    if close is None:
        add("deadline", "none", WEIGHTS["deadline"] // 2)
    else:
        days = (date.fromisoformat(close) - today).days
        if days >= MIN_PREP_DAYS:
            add("deadline", "ample", WEIGHTS["deadline"], days=days)
        elif days >= TIGHT_PREP_DAYS:
            add("deadline", "tight", WEIGHTS["deadline"] // 2, days=days)
        elif days >= 0:
            add("deadline", "urgent", 0, days=days)
        else:
            add("deadline", "passed", 0)

    return total, reasons


def rank(profile, opportunities, eligibility, min_score=0, today=None,
         templates=None, labels=None):
    """Score one profile against many opportunities, best first.

    `opportunities` is any iterable of opportunity dicts (each needs an `id`);
    `eligibility` maps an opportunity id to its eligible org types.

    Returns `[{"opp": ..., "score": int, "reasons": [Reason, ...]}]` in a
    fully deterministic order: score descending, then soonest deadline
    (opportunities with no deadline last), then id - so two runs over the same
    catalog always produce the same list.
    """
    ranked = []
    for opp in opportunities:
        value, reasons = score(
            profile, opp, eligibility.get(opp["id"]) or (),
            today=today, templates=templates, labels=labels)
        if value >= min_score:
            ranked.append({"opp": opp, "score": value, "reasons": reasons})
    ranked.sort(key=lambda m: (-m["score"],
                               m["opp"].get("close_date") is None,
                               m["opp"].get("close_date") or "",
                               m["opp"]["id"]))
    return ranked
