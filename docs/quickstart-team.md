# Team quickstart (Tier 2 reviewer queue)

Run the shared reviewer app against a local Supabase stack: queue, four-column
board, assignee/status workflow, SLA badges, autohide and the decision audit log.
Run the blocks in order from the repo root (PowerShell shown).

## 1. Start the local stack

```powershell
supabase start
```

Wait for `supabase local development setup is running`. This project uses ports
**55321** (API) / **55322** (DB) / **55323** (Studio), so it does not clash with
other local Supabase projects. The schema is three squashed migrations
(`supabase/migrations/0001_schema.sql` + `0002_logic.sql` + `0003_team.sql`);
if you edited a migration, re-apply with `supabase db reset` before continuing.

## 2. Seed the judge defaults

```powershell
uv run persocial bootstrap
```

Idempotent. Seeds the judge model row, prompt v1 and the lexicon from
`PERSOCIAL_PACKS` (default `generic`; `generic,gulf_ar` for Gulf/MSA/Egyptian
Arabic + Arabizi); add `--demo` to also load the synthetic `examples/sample/` data. Needs only the local database — no keys, no network.

## 3. Point the web app at the local stack

Create `web/.env.local` (gitignored, never commit) with the values from
`supabase status -o env`:

```dotenv
VITE_SUPABASE_URL=http://127.0.0.1:55321
VITE_SUPABASE_ANON_KEY=<ANON_KEY>
# VITE_PERSOCIAL_TZ=UTC
VITE_GUEST_LOGIN=true   # demo only, see "Guest login" below
```

Or copy `web/.env.example`.

### Guest login (demo only)

With `VITE_GUEST_LOGIN=true` the login screen shows **Continue as guest**
(Supabase anonymous sign-in, enabled locally by `enable_anonymous_sign_ins = true`
in `supabase/config.toml`). Migration `0004_guest.sql` maps anonymous sessions to a
restricted reviewer: they can read shared data and triage comments, but are never
admin and cannot read settings (except `sla_hours`), models, prompts or the lexicon,
and cannot manage members. Load demo data with `persocial bootstrap --demo`.

**Turn it off for any real deployment:** set `VITE_GUEST_LOGIN=false` (or remove
it) and set `enable_anonymous_sign_ins = false` in `supabase/config.toml` / the
Supabase dashboard (Authentication > Sign In / Providers).

## 4. Run the reviewer app

```powershell
cd web
npm ci
npm run dev
```

Open http://127.0.0.1:5180. On first visit you see the login screen:

- **Google OAuth** — works when the project has a Google provider configured.
- **Email magic link** — enter any invited email, open the login link from the
  local Inbucket at http://127.0.0.1:55324, paste the code.

A signed-in user with no row in `members` sees "Not on the list". An admin
adds them from **Members → Add & invite**, which also sends the magic-link
email. (`persocial bootstrap` does not create members; the first admin row is
inserted by hand, e.g. via Studio at http://127.0.0.1:55323.)

## 5. Try the review loop

1. **Upload** (admin): post an `apify_comments` CSV/JSON or a
   `generic_comments_csv` (see `docs/input-format.md`; synthetic fixtures in
   `examples/sample/`). Scoring + judge run as usual; undecided flagged comments land in the queue.
2. **Inbox → Board**: four columns (`new` → `assigned` → `in_review` →
   `done`). Drag a card to change its workflow status; use **assign to me**.
   Cards older than `sla_hours` (setting, default 24) carry a red SLA badge.
3. **Decide** on a Sheet or Post page as usual (hide / keep / escalate).
4. **History**: the clock button on any comment opens its drawer — workflow
   controls plus the audit timeline (`comment_events`: every decision,
   assignee, status and IG-action change with actor and timestamp).

## 6. Verify

Seed six synthetic comments (five flagged) plus a member, then run the
data-layer smoke test (21 checks) with the values from
`supabase status -o env`:

```powershell
cd ..
uv run python scripts/seed_smoke.py --email smoke@example.com
node web/scripts/smoke.mjs <API_URL> <ANON_KEY> <SERVICE_ROLE_KEY> smoke@example.com
```

Every check prints `ok` and ends with `ALL OK` — including
`queue_comments`, the board status/assignee move and the audit-timeline
read. The seed is idempotent and the smoke test reverts its own moves, so
re-running needs no reset.

## Ports and services

| What | Where |
|---|---|
| Web app (`npm run dev`) | http://127.0.0.1:5180 |
| Supabase API / Studio / Inbucket | http://127.0.0.1:55321 / :55323 / :55324 |
| Postgres | `postgresql://postgres:postgres@127.0.0.1:55322/postgres` |
