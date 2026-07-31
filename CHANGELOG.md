# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.1.0

First release.

### Added

- `grants_gov` — Grants.gov connector. Paged `search2` sweep, per-id
  `fetchOpportunity` detail fetch, and normalization of both into flat dicts:
  coded applicant types map to org-type keys, coded funding categories map to
  focus areas, and the three upstream date formats normalize to ISO. Transport
  faults retry with doubling backoff; a 4xx never does. `date_range_since` and
  `since_fetcher` implement date-filtered sweeps against the discrete "last N
  days" buckets the API actually offers, always rounding the window up.
- `propublica` — ProPublica Nonprofit Explorer connector. EIN normalization,
  a single-request lookup reduced to a profile prefill, `diff_profile` for
  stored-vs-registry comparison that never proposes erasing a value from an
  upstream blank, and a paced `scan_profiles` bulk pass that survives an
  individual failed lookup.
- `matching` — deterministic 0–100 fit scoring across five weighted
  dimensions (org type 30, geography 25, focus 25, award size 10, deadline
  10). Every dimension emits exactly one `Reason` carrying its points and a
  rendered sentence, and the reasons always sum to the score. Unknowns earn
  partial credit rather than zero. Reason wording is templated and
  overridable; the clock is injectable via `today=`.
- `vocabulary` — the upstream code lists (Grants.gov applicant types and
  funding categories, NTEE major groups, USPS state codes, opportunity
  statuses) mapped onto stable canonical keys, plus display labels, the
  politeness interval, and the required Grants.gov attribution notice.
- `text.plain_text` — the normalization every fetched string passes through:
  tags stripped, entities unescaped, whitespace collapsed, length capped.

### Notes

- No runtime dependencies and no API keys. `urllib` from the standard library
  is the entire transport.
- The test suite is fully offline. The Grants.gov fixtures are recorded
  envelopes (with the response JWT, the named agency contact and an unused
  42 KB revision history removed); the ProPublica fixture is synthetic.
