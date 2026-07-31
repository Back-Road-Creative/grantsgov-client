# Security Policy

## Supported versions

Only the latest released tag receives fixes. Pin a released `v*` tag; `main`
is unstable.

## Reporting a vulnerability

Please report suspected vulnerabilities privately. Do **not** open a public
issue for a security report.

Use GitHub's **Security → Report a vulnerability** tab on this repository
(Private Vulnerability Reporting). That is the private channel; it reaches the
maintainers without disclosing anything publicly.

If that tab is unavailable to you, open a public issue containing **no
technical detail** — just a request for a private channel — and one will be
opened for you.

Please include the affected version or commit, a description of the issue and
its impact, reproduction steps, and any suggested remediation.

## What to expect

- Acknowledgement within 5 business days.
- An initial assessment and severity triage within 10 business days.
- Coordinated disclosure: we agree a timeline with you before any public
  write-up, and credit reporters who want it.

## Scope and threat model

This library makes outbound HTTPS requests to two public APIs and parses what
comes back. The interesting surface is therefore what it does with a hostile
or malformed response.

**In scope**

- Anything that lets upstream content escape normalization — `plain_text` is
  the chokepoint: tags stripped, entities unescaped, whitespace collapsed,
  length capped. Nothing fetched is executed, no URL in a payload is followed,
  and no response is written to disk.
- Unbounded resource use driven by a response: a payload that defeats the
  length cap, a sweep that cannot terminate, a retry loop that becomes a
  hammer.
- Anything that causes the library to send more traffic than the documented
  pacing, or to retry a 4xx.
- A malformed envelope producing something other than a `ConnectorError` or a
  quarantined (`None`) record.

**Out of scope**

- The accuracy or availability of the upstream APIs, and any change they make
  to their contract.
- The fit-scoring weights. They are an opinion, not a security control; a
  score you disagree with is not a vulnerability.
- Anything about how *your* application stores what this library returns —
  this library keeps no state, opens no database and writes no files.
- Deliberately calling the connectors with a caller-supplied endpoint or path.
  `API_BASE` is fixed in both modules; if you edit it, that is your trust
  boundary now.

## A note on data handling

An EIN and an organisation's registration record are public, but they are
still somebody's records. This library holds them in memory and hands them
back; it never logs, caches or transmits them anywhere else. If you build on
it, keep that property.
