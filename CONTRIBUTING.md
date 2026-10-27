# Contributing

Persocial is an extraction, not a framework: small, explicable, synthetic
data only. Every contribution must keep the gates in `docs/` green
(`quickstart-solo.md` verbatim, `quickstart-team.md` verbatim, `pytest`,
`ruff`, `npm run build`, `smoke.mjs`).

## Ground rules

- **Synthetic data only.** No real comments, usernames or media — not in code,
  fixtures, screenshots or GIFs. Every sample username starts with `demo_`,
  every sample id with `9000`. The review gate rejects anything else.
- One parser truth: the Python parser (`persocial/ingest/parsers.py`) and the
  web parser (`web/src/lib/parse.ts`) share `shared/input-aliases.json`.
  Change one and the three-file parity test (`tests/test_adapters.py`) must
  still pass; change both together.
- Reuse, don't rewrite: `select.py`, `rules.py`, `client.py`, `runner.py`,
  `claims.py`, `text.py` and `scoring/core.py` are the shared core. Tier 1
  adapts at the store boundary (`persocial/local/`), never inside them.
- DB tests live in modules marked `pytestmark = pytest.mark.db`; pure files
  (`test_local`, `test_adapters`, `test_golden`, `test_judge_parse`,
  `test_notebook`) must import without `psycopg`, `torch` or a database.

## Adding a region pack

1. Create `persocial/judge/packs/<name>.py` exporting `LEXICON`
   (list of `(term, kind)`), `PROMPT_APPENDIX` (plain text) and `NORM_HINTS`
   (list of `(from, to)` literal replacements) — all optional.
2. Register it in `PACKS` in `persocial/judge/packs/__init__.py`.
3. Add tests in `tests/test_packs.py`: kinds must be schema-valid, no
   political/regime terms (the suite enforces this).
4. Re-bootstrap (`persocial bootstrap`, or wipe the DB): the prompt appendix
   and pack lexicon seed the database only when empty — changing
   `PERSOCIAL_PACKS` later does not mutate existing rows (edit via Judge Lab).
5. Document the pack in `docs/taxonomy.md`.

## Adding an input adapter

1. Extend `detect()` + `parse_file()` in `persocial/ingest/parsers.py`
   (defensive: ignore unknown keys, never crash on odd shapes).
2. Mirror the branch in `web/src/lib/parse.ts` using the shared alias map.
3. Add the `uploads.source` value to the schema CHECK and the sheet-creation
   branch.
4. Add fixtures + tests in `tests/test_adapters.py`, including parity across
   all shapes for the overlapping fields and the re-run-adds-0 check.
5. Document the contract in `docs/input-format.md`.

## Adding a platform (v0.2+)

Read the deferred design first (`plan.md` §Deferred, WP-D1): `ig_id` →
`external_id`, `ig_action` → `platform_action`, per-platform URL templates.
Do the rename as its own change before adding any platform code.

## Pull requests

See `.github/PULL_REQUEST_TEMPLATE.md`. Small diffs, CRLF line endings,
no secrets, no real data.
