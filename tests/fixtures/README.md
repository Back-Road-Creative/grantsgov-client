# Test fixtures

The suite runs entirely offline. Every test drives a `fetcher` callable that
returns one of these files, so nothing here touches the network — which is
also why the suite is fast and why it never depends on what happens to be
posted today.

## `search2_posted.json`, `fetch_opportunity.json`

Recorded envelopes from the public Grants.gov API:

- `search2_posted.json` — `POST https://api.grants.gov/v1/api/search2`,
  body `{"rows": 5, "keyword": "food security", "oppStatuses": "posted"}`.
  Hits are **shallow**: `id, number, title, agency, agencyCode, openDate,
  closeDate, oppStatus, docType, cfdaList` and nothing else. Paging is by
  `startRecordNum`, and `data.dateRangeOptions` is where the "last N days"
  buckets in `grants_gov.DATE_RANGE_BUCKETS` come from.
- `fetch_opportunity.json` — `POST https://api.grants.gov/v1/api/fetchOpportunity`,
  body `{"opportunityId": 361403}`. The rich record: `synopsis.synopsisDesc`,
  `synopsis.applicantTypes` (coded id + description),
  `synopsis.fundingActivityCategories`, `synopsis.awardFloor` /
  `awardCeiling`, and `synopsis.responseDate` — the deadline, in the verbose
  `Aug 03, 2026 12:00:00 AM EDT` form.

The content is a real, public federal funding notice — that is the point, it
pins the shape of what the API actually sends. Three edits were made to the
recorded bytes before they were committed:

1. the per-response JWT in the envelope's `token` field is blanked,
2. the named agency contact (an individual's name, direct e-mail and direct
   phone) is replaced with a generic office and `grants@example.gov`,
3. `data.opportunityHistoryDetails` — 42 KB of prior revisions no code path
   in this library reads — is dropped.

Nothing else is altered.

## `propublica_org.json`

**Synthetic**, authored for this repository. It matches the shape of a
ProPublica Nonprofit Explorer `organizations/<ein>.json` response, but the
organisation, the address and every financial figure are invented, and the
EIN is `000000000` — the IRS has never issued a prefix of `00`, so it cannot
collide with a real filer.

Do not replace it with a recording of a real organisation. An EIN is a public
identifier, but a checked-in one turns a test fixture into a permanent,
searchable record of somebody's finances.

## Re-recording

If the upstream contract changes, re-record deliberately by issuing the same
requests above, then re-apply the three edits listed for the Grants.gov files.
Never re-record from CI, and never point a re-recording at a live
organisation's EIN.
