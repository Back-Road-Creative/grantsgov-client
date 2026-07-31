# Contributing

Thanks for taking a look. This is a small library with a narrow job, so the
bar for a change is "does it make the connectors or the scorer more honest",
not "does it add a feature".

## Setup

```bash
git clone <this repository>
cd grantsgov-client
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

Python 3.11 or newer. There are no runtime dependencies and there should not
be any — see the rule below.

## The gates

CI runs these on every push and pull request. Run them first:

```bash
pytest -q
ruff check .
```

## Rules that are not negotiable

- **No runtime dependencies.** "Zero dependencies, zero API keys" is the
  headline; a `dependencies = []` that quietly grows an entry makes the README
  a lie. Test-only and lint-only tools go in the `dev` extra.
- **The suite stays offline.** Every function that reaches the network takes an
  injectable `fetcher`, and `sleep` is injectable too. A test that touches the
  network or actually waits will be sent back.
- **Never weaken or delete a test to make the suite pass.** For a bug fix, add
  the failing test first and watch it fail.
- **No real EINs, no real organisations, in fixtures.** See
  `tests/fixtures/README.md`. Public federal opportunity listings are fine;
  a private organisation's registration record is not.
- **Politeness is a feature.** Do not remove the pacing pause, do not retry a
  4xx, and do not let backoff shrink below the pacing interval.
- **Docs land with the code.** A change to behaviour updates the README (and
  the scoring table, if you touched a weight) in the same commit.

## Changing the scorer

The weights are one defensible opinion, not a validated model, and reasonable
people will want different ones. Before proposing a change:

- keep `sum(WEIGHTS.values()) == 100`,
- keep every dimension emitting exactly one `Reason` whose points sum to the
  total (`test_every_point_is_accounted_for_by_a_reason` pins this),
- keep unknown scoring above a stated mismatch and below a stated match, and
- add the new branch's key to `REASON_TEMPLATES` — a branch with no template
  fails `test_every_template_key_is_reachable_and_every_branch_has_one`.

If you just want different wording or a different language, you do not need a
pull request: pass your own `templates=` mapping.

## Commits and pull requests

- Conventional commit subjects (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).
- One logical change per pull request, with the gate output in the
  description.
- Add a `## Unreleased` entry to `CHANGELOG.md` for anything user-visible.

## Reporting

- Bugs and ideas: open an issue.
- Security: do **not** open a public issue — follow [`SECURITY.md`](SECURITY.md).
