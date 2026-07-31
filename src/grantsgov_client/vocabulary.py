"""The coded vocabularies the upstream APIs speak, mapped onto a small
canonical set a consumer can reason about.

Everything here is derived from public, upstream-published code lists:
Grants.gov applicant-type and funding-activity-category ids, the NTEE major
groups the IRS assigns, and the USPS state codes. The canonical keys on the
right-hand side of each map are this library's own — pick your own labels if
you like, but keep the keys stable, because the connectors and the scorer
both speak them.
"""

# --- Opportunity status -----------------------------------------------------
# Adopted from Grants.gov verbatim rather than re-encoded.

OPPORTUNITY_STATUSES = ("posted", "forecasted", "closed", "archived")
OPEN_STATUSES = ("posted", "forecasted")
STATUS_LABELS = {"posted": "Open", "forecasted": "Forecasted",
                 "closed": "Closed", "archived": "Archived"}

# --- Organization types -----------------------------------------------------
# The eligibility axis. Grants.gov applicant-type codes map onto it.

ORG_TYPES = (
    ("nonprofit_501c3", "Nonprofit (501(c)(3))"),
    ("nonprofit_other", "Nonprofit (other)"),
    ("government_state", "State government"),
    ("government_local", "City / county / district government"),
    ("tribal", "Tribal government / organization"),
    ("school_district", "School district"),
    ("higher_ed", "Higher education"),
    ("housing_authority", "Housing authority"),
    ("small_business", "Small business / for-profit"),
    ("individual", "Individual"),
    ("other", "Other"),
)
ORG_TYPE_KEYS = tuple(k for k, _ in ORG_TYPES)

# Grants.gov `synopsis.applicantTypes[].id` -> org type. Code "99"
# (unrestricted) is not listed: it expands to every org type at normalization
# time, which is a rule, not a mapping.
GRANTS_GOV_APPLICANT_MAP = {
    "00": "government_state", "01": "government_local",
    "02": "government_local", "04": "government_local",
    "05": "school_district", "06": "higher_ed", "07": "tribal",
    "08": "housing_authority", "11": "tribal", "12": "nonprofit_501c3",
    "13": "nonprofit_other", "20": "higher_ed", "21": "individual",
    "22": "small_business", "23": "small_business", "25": "other",
}
UNRESTRICTED_APPLICANT_CODE = "99"

# --- Focus areas ------------------------------------------------------------

FOCUS_AREAS = (
    ("agriculture", "Agriculture"),
    ("arts", "Arts & Culture"),
    ("business", "Business & Commerce"),
    ("community_dev", "Community Development"),
    ("disaster", "Disaster Prevention & Relief"),
    ("education", "Education"),
    ("employment", "Employment & Workforce"),
    ("energy", "Energy"),
    ("environment", "Environment"),
    ("food_nutrition", "Food & Nutrition"),
    ("health", "Health"),
    ("housing", "Housing"),
    ("humanities", "Humanities"),
    ("social_services", "Income Security & Social Services"),
    ("justice", "Law, Justice & Legal Services"),
    ("natural_resources", "Natural Resources"),
    ("regional_dev", "Regional Development"),
    ("science_tech", "Science & Technology"),
    ("transportation", "Transportation"),
    ("other", "Other"),
)
FOCUS_AREA_KEYS = tuple(k for k, _ in FOCUS_AREAS)

# Grants.gov `synopsis.fundingActivityCategories[].id` -> focus area.
# Anything unmapped normalizes to "other".
GRANTS_GOV_CATEGORY_MAP = {
    "AG": "agriculture", "AR": "arts", "BC": "business", "CD": "community_dev",
    "CP": "other", "DPR": "disaster", "ED": "education", "ELT": "employment",
    "EN": "energy", "ENV": "environment", "FN": "food_nutrition",
    "HL": "health", "HO": "housing", "HU": "humanities",
    "ISS": "social_services", "IS": "other", "LJL": "justice",
    "NR": "natural_resources", "RD": "regional_dev", "ST": "science_tech",
    "T": "transportation", "ACA": "health", "RA": "other", "O": "other",
}

# --- Geography --------------------------------------------------------------
# "US" (national) or a single state / district code.

US_STATES = (
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI",
    "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN",
    "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
    "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA",
    "WV", "WI", "WY",
)
NATIONAL = "US"
GEOGRAPHIES = (NATIONAL, *US_STATES)

# --- Amount bands -----------------------------------------------------------
# One axis, used twice: the size of an award, and the size of award an
# organization can realistically manage.

AMOUNT_BANDS = (
    ("under_25k", "Under $25k", 0, 25_000),
    ("k25_100k", "$25k-$100k", 25_000, 100_000),
    ("k100_500k", "$100k-$500k", 100_000, 500_000),
    ("k500_1m", "$500k-$1M", 500_000, 1_000_000),
    ("over_1m", "Over $1M", 1_000_000, None),
)
AMOUNT_BAND_KEYS = tuple(k for k, _, _, _ in AMOUNT_BANDS)
AMOUNT_BAND_RANGE = {k: (lo, hi) for k, _, lo, hi in AMOUNT_BANDS}

# --- NTEE ------------------------------------------------------------------
# IRS NTEE major-group letter -> focus area. Used to seed a focus area from an
# EIN lookup; a letter with no entry simply yields no seed.

NTEE_FOCUS_MAP = {
    "A": "arts", "B": "education", "C": "environment", "D": "environment",
    "E": "health", "F": "health", "G": "health", "H": "health",
    "I": "justice", "J": "employment", "K": "food_nutrition", "L": "housing",
    "M": "disaster", "N": "community_dev", "O": "education",
    "P": "social_services", "R": "justice", "S": "community_dev",
    "U": "science_tech", "V": "science_tech",
}

# --- Display labels ---------------------------------------------------------
# One lookup for every canonical key this library emits. Callers that render
# their own labels can ignore it; the scorer uses it for reason text.

LABELS = {
    **dict(ORG_TYPES), **dict(FOCUS_AREAS), **STATUS_LABELS,
    **{k: label for k, label, _, _ in AMOUNT_BANDS},
    NATIONAL: "National (US)",
}

# --- Politeness -------------------------------------------------------------
# Neither API publishes a numeric rate limit and neither requires a key, so
# the pacing below is voluntary: roughly one request a second. The often
# quoted 60/min + 10,000/day figures belong to the separate, *keyed*
# Simpler.Grants.gov API - they do not apply to the classic endpoints this
# library calls.

REQUEST_PAUSE = 1.1  # seconds between calls
PAGE_ROWS = 100      # search2 page size

# Required by the Grants.gov API terms of service. Show it wherever you
# surface data fetched through this library.
GRANTS_GOV_ATTRIBUTION = (
    "This product uses the Grants.gov API but is not endorsed or certified by"
    " the U.S. Department of Health and Human Services.")
