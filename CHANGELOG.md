# Changelog

## v0.1.0

First open-source cut. Two tiers, one pipeline.

**Tier 1 Solo** — headless CLI, no server, no login:

- `persocial run INPUT [--out triage] [--format xlsx,csv,html] [--packs ...]
  [--no-judge] [--device cpu]` — parse → SQLite store → local HF scoring →
  judge → `triage.xlsx` / `triage.csv` / self-contained `triage.html`.
- Incremental re-runs (stored comments add 0), NLP-only fallback,
  `persocial models pull` + `persocial doctor`.

**Tier 2 Team** — Supabase + React reviewer queue:

- Four-column board (`new` → `assigned` → `in_review` → `done`), drag to
  move, assign-to-me, SLA badges from `sla_hours`.
- Decision audit log (`comment_events` + trigger) with actor + timestamp,
  shown in the comment drawer.
- Google OAuth + email magic-link login, member invite from Members.
- Squashed schema (`0001_schema` + `0002_logic` + `0003_team`).

**Shared core** — Apify CSV/JSON + generic CSV input adapters (single alias
map, parity-tested), neutral moderation taxonomy with `generic` + `gulf_ar`
region packs (Arabic dialects + Arabizi), 300-comment synthetic sample set,
80-case Arabic golden eval, packaging extras
(base / `[scoring]` / `[team]` / `[dev]`), four-job CI, launch docs.
