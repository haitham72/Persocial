# Roadmap

Tier 1 Solo and Tier 2 Team are v0.1. Tier 3 is planned work, in priority
order. "Not planned" is explicit scope defence — don't build it by accident.

## Tier 3 (planned)

1. **Scheduled Apify pulls.** Document the Apify API recipe in
   `docs/input-format.md` first; then a pull scheduler (cron, not a daemon)
   that fetches new comments on owned posts into the existing ingest path.
   Upload stays manual until this lands.
2. **Second platform.** TikTok or YouTube comments through the same pipeline.
   Deferred design (WP-D1): `ig_id` → `external_id`,
   `ig_action` → `platform_action`, per-platform URL templates. That rename
   is v0.2 work, not a drive-by.
3. **Student-model fine-tune loop.** `persocial dataset` already exports the
   judge-call training set (`single` / `agree` / `human` tiers); the loop
   trains a small student scorer from it (export format documented, WP-D2).
   No trainer code in v0.1.

## Not planned

- Multi-account agencies, role hierarchies beyond admin/reviewer.
- Native hide/reply via the Instagram API (decisions are executed by hand;
  `ig_action` only records what was done).
- Publishing/scheduling, analytics dashboards beyond the queue counters.
- Hosted SaaS or managed inference — the tool runs on your machine and your
  database, with your LLM endpoint.
