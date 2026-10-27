# Security

## What leaves the machine

Exactly one thing, and only if you configure it: **LLM judge calls**.
`persocial run` (without `--no-judge`) and the Team worker POST flagged
comment texts to `PERSOCIAL_JUDGE_BASE_URL` (default
`http://127.0.0.1:1234/v1` — a local server such as LM Studio or Ollama).
Point it at a remote endpoint and those texts go there; nothing else does.

Everything else stays local:

- Scoring runs on-device (`torch`/`transformers`, `--device cpu` default).
- Solo state lives in `./.persocial/persocial.db` (gitignored).
- Team state lives in your Supabase project (local stack or yours).
- Sample and fixture data is synthetic (`demo_*` usernames, `9000*` ids).

## What never enters the repo

Real comment exports, real usernames, media thumbnails, `.env` files,
`web/.env.local`, `web/.env.production`, `storage/` uploads, `*.xlsx`
reports. All are gitignored; CI also runs a secret scan (gitleaks) on
every push.

## Data retention

- Solo: delete `./.persocial/` to wipe the local store and reports.
- Team: comments carry the full life (text → scores → judge → decision).
  Deleting a post cascades to its comments, sheets and uploads.
  Judge calls are kept as the fine-tuning set (`persocial dataset` export);
  drop `judge_calls` rows if you need them gone.

## Reporting

Open a private issue with the version (`persocial doctor` output) and a
synthetic repro. Never attach real exports.
