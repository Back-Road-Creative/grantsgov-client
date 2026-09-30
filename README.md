# grantsgov-client

Keyless Python connectors for two public US funding datasets, plus an
explainable fit scorer.

- **Grants.gov** — sweep every posted or forecasted federal opportunity, fetch
  the rich record for any one of them, and get back flat dicts with dates,
  amounts and eligibility already normalized.
- **ProPublica Nonprofit Explorer** — look up an EIN and get back the handful
  of fields an organisation profile actually wants.
- **Fit scoring** (optional) — score an organisation against an opportunity,
  0–100, where every point traces to a sentence you can show a human.

**Zero API keys. Zero runtime dependencies.** `urllib` from the standard
library is the entire transport.

```bash
pip install grantsgov-client
```

Python 3.11+.

## Why this exists

Both APIs are free and open, and both are a little awkward:

- Grants.gov `search2` returns **shallow** hits — id, title, agency, dates,
  status, and nothing else. The synopsis, the eligible applicant types, the
  award floor and ceiling and the real deadline all live behind a second,
  per-opportunity `fetchOpportunity` call. Any useful sync is therefore
  *sweep, then enrich*, and you have to build that yourself.
- The interesting fields arrive as coded ids (`applicantTypes[].id == "12"`)
  and as three different date formats (`06/22/2026`,
  `Aug 03, 2026 12:00:00 AM EDT`, and ISO), so "is this open, to whom, for how
  much" needs a translation layer before it is a query.
- Neither API publishes a rate limit, which is not the same as not having one.

This library is that translation layer, with the politeness built in.

## Quick start

### Sweep and enrich

```python
from grantsgov_client import grants_gov

rows = []
for hit in grants_gov.sweep(statuses="posted"):
    row = grants_gov.normalize_hit(hit)
    if row is None:
        continue                      # unusable record - set it aside
    detail = grants_gov.fetch_detail(grants_gov.http_fetch,
                                     row["source_record_id"])
    fields, eligible_org_types = grants_gov.normalize_detail(detail)
    rows.append({**row, **fields, "org_types": eligible_org_types})

print(rows[0])
# {'source_record_id': '361403',
#  'opp_number': 'HHS-2026-ACL-AOD-DFLA-0025',
#  'title': 'Expanding Financial Literacy and Empowerment: ...',
#  'funder_name': 'Administration for Community Living',
#  'open_date': '2026-06-22', 'close_date': '2026-08-03',
#  'status': 'posted', 'raw_url': 'https://www.grants.gov/...',
#  'synopsis': 'This grant is funded under ...',
#  'amount_floor': 1000000.0, 'amount_ceiling': 1200000.0,
#  'category': 'social_services',
#  'org_types': ['government_local', 'higher_ed', 'nonprofit_501c3', ...]}
```

`sweep` is a generator that pages until upstream runs out, pausing between
pages. Stop iterating and the requests stop too.

### Only what changed since last time

`search2` filters on **posted** date, in fixed "last N days" buckets rather
than an arbitrary since-date. `date_range_since` picks the smallest bucket
that fully covers your gap, always rounding **up**:

```python
last_sync = "2026-07-20T00:00:00Z"                   # when you last swept
date_range = grants_gov.date_range_since(last_sync)  # "3", "7", "14", ... or None
if date_range is None:
    fetcher = grants_gov.http_fetch          # gap too wide: sweep everything
else:
    fetcher = grants_gov.since_fetcher(grants_gov.http_fetch, date_range)

for hit in grants_gov.sweep(fetcher):
    ...
```

`None` means "no bucket covers this" — never fetched, an unparseable stamp, or
a gap wider than the widest bucket (56 days). In all three cases you owe a
full sweep.

One warning worth repeating: because the filter is on *posted* date, an edit
to an already-posted opportunity does not come back through it. A filtered
sweep **supplements** a full one; it never replaces it. In particular, an
opportunity missing from a filtered sweep is not gone — do not treat absence
from a filtered result as a close signal.

### EIN lookup

```python
from grantsgov_client import propublica

ein = propublica.normalize_ein("00-0000000")   # -> '000000000', or None
prefill = propublica.lookup(ein)
# {'name': ..., 'city': ..., 'state': 'OH', 'ntee_code': 'K30',
#  'focus_area': 'food_nutrition', 'annual_revenue': 320000.0,
#  'org_type': 'nonprofit_501c3', 'capacity_band': 'k100_500k'}
```

`diff_profile(stored, fresh)` compares what you hold against what the registry
says and returns only genuine disagreement. An upstream **blank is never a
difference** — a gap in the registry must not propose erasing a value you
already have — and only the fields in `REFRESHABLE_FIELDS` are considered, so
a scrape can never overwrite an organisation's own name.

`scan_profiles(rows)` runs that over many records, paced, yielding
`(row, drift, error)` per record. One failed lookup yields an error string and
the pass continues.

### Fit scoring

```python
from grantsgov_client.matching import rank, score

profile = {"org_type": "nonprofit_501c3", "state": "OH",
           "geographies": ["OH"], "focus_areas": ["food_nutrition"],
           "capacity_band": "k25_100k"}

total, reasons = score(profile, opportunity, eligible_org_types)
print(total)                              # 100
for reason in reasons:
    print(f"{reason.points:+3d}  {reason}")
# +30  Eligible organization type: Nonprofit (501(c)(3))
# +25  Serves OH
# +25  Focus area matches: Food & Nutrition
# +10  Award size fits the capacity band
# +10  45 days to prepare
```

Five dimensions, fixed weights, no model and no randomness:

| Dimension | Weight | Full credit | Partial credit (unknown) | Zero |
|---|---:|---|---|---|
| Organization type | 30 | profile type is in the eligible list | 10 — listing did not state eligibility, or profile has no type | stated type, stated list, no overlap |
| Geography | 25 | opportunity's state is served or is the home state<br>(20 for a national opportunity) | 5 — opportunity states no geography, or profile states none | opportunity is for a state the profile does not serve |
| Focus area | 25 | opportunity's category is in the profile's focus areas | 5 — category is `other`/absent, or profile lists none | stated category outside the profile's focus areas |
| Award size | 10 | award range overlaps the capacity band | 5 — no capacity band, or no amounts posted | stated amounts outside the band |
| Deadline | 10 | 14+ days to prepare | 5 — no deadline posted<br>5 — 7–13 days (tight) | under 7 days, or already passed |

Two rules the table encodes:

- **Unknown is not a no.** Silence earns partial credit on every dimension.
  A listing that does not state eligibility is a maybe, not a rejection.
- **Every point has a reason.** Each dimension appends exactly one `Reason`
  carrying its `dimension`, a branch `code`, the `points` it contributed, and
  rendered `text`. `sum(r.points for r in reasons) == total`, always — the
  test suite pins that.

`rank(profile, opportunities, eligibility)` scores many at once and sorts
deterministically: score descending, then soonest deadline (no deadline last),
then id. Identical inputs always produce an identical list.

Both take `today=` — pass a `datetime.date` and deadline scoring stops
depending on the wall clock, which is what makes the scores reproducible in
a test or a batch job.

Re-word or translate any line without touching the arithmetic:

```python
score(profile, opportunity, eligible,
      templates={"geography.match": "Serves the state of {geography}"})
```

`matching.REASON_TEMPLATES` is the full set of keys.

## Testing your own code against this

Every function that reaches the network takes a `fetcher` callable, so you can
run entirely offline:

```python
def fake_fetch(endpoint, payload):
    return {"errorcode": 0, "data": {"oppHits": [...], "hitCount": 1}}

list(grants_gov.sweep(fake_fetch, sleep=lambda seconds: None))
```

`sleep` is injectable too, so a suite never actually waits. This library's own
tests use exactly this seam — see `tests/`.

## Politeness and failure handling

- **Pacing.** Roughly one request per second (`vocabulary.REQUEST_PAUSE`), by
  choice. Neither API publishes a numeric rate limit; the widely quoted
  60/minute + 10,000/day figures belong to the separate, *keyed*
  Simpler.Grants.gov API and do not apply here.
- **Retries.** Transport faults only — resets, DNS failures, timeouts, and
  5xx. Backoff doubles from the pacing pause, so a struggling server sees
  strictly *less* traffic than a healthy one. Three attempts, then it raises.
- **A 4xx is never retried.** It means the request was wrong; repeating it is
  just hammering.
- **A malformed response is one error.** `sweep` and `fetch_detail` raise
  `ConnectorError` for an upstream `errorcode` other than 0 and for a body that
  is not a JSON object (a list, a string, null), and for a success envelope
  whose `data` is missing or not an object. Nothing else escapes from a bad
  payload, so one `except ConnectorError` covers every upstream failure that
  is not a transport fault. An empty `data` object is valid and yields no hits.
- **A bad record is quarantined, not fatal.** `normalize_hit` returns `None`
  for a record with no id, no title, or an unrecognised status, so one broken
  row out of thousands does not abort a sweep.
- **Untrusted by default.** Everything fetched is normalized to plain text —
  tags stripped, entities unescaped, whitespace collapsed, length capped.
  Nothing fetched is executed, and no URL in a payload is followed.

## Honest limits

- **Grants.gov only, federal only.** State portals and private foundations are
  not covered. Neither is the newer Simpler.Grants.gov API, which needs a key.
- **`search2` cannot tell you what changed.** Its only date filter is on
  posted date. To notice an edited opportunity you must re-fetch its detail.
- **Nothing here manages state.** No database, no cache, no dedupe, no "what
  did I see last time". This library normalizes; persistence is yours.
- **Detail fetches are one request each.** A sweep of a few thousand
  opportunities is a few thousand paced requests. Budget for it, and cap the
  enrichment per run.
- **The fit scorer's weights are one opinion.** They are a defensible starting
  point, not a validated model, and they are deliberately easy to read and
  change. It does not read the notice text; it compares coded fields.
- **ProPublica's data is the IRS Business Master File.** It lags reality by
  months, and small filers can be missing entirely. Treat a lookup as a
  prefill to be confirmed, never as a verified fact.
- **Both APIs can change without notice.** The recorded fixtures under
  `tests/fixtures/` pin the shape this library was written against.

## Attribution

The Grants.gov API terms require this notice wherever you surface data fetched
through it (also available as `vocabulary.GRANTS_GOV_ATTRIBUTION`):

> This product uses the Grants.gov API but is not endorsed or certified by the
> U.S. Department of Health and Human Services.

ProPublica's Nonprofit Explorer API is free to use; credit ProPublica and the
IRS as the data source.

## License

MIT — see [LICENSE](LICENSE).
