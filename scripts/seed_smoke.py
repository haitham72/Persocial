"""Seed the local Supabase stack for `web/scripts/smoke.mjs` (CI job 3 + local runs).

Inserts a member, one account/post/upload/sheet and six synthetic SMK comments
(five flagged) with plain INSERTs — the audit trigger is UPDATE-only, so seeding
stays out of `comment_events`. Idempotent: every insert is upsert-or-ignore, and
the smoke test reverts its own board/decision moves, so re-running needs no reset.

Usage:
    uv run python scripts/seed_smoke.py [--email member@example.com]
"""

from __future__ import annotations

import argparse

from persocial import db

ACCOUNT = "demo_bakery"
POST = "SMK001"
SHEET_N_NEW = 6
SHEET_N_FLAGGED = 5

SEED_COMMENTS = [
    # (ig_id, author, text, verdict, category, severity)
    ("SMK9000", "demo_ana", "Win a phone, click my link now cheap cheap", "hide", "spam_scam", 3),
    ("SMK9001", "demo_omar", "You are a fool, delete your account", "review", "harassment", 2),
    ("SMK9002", "demo_lina", "Promo promo follow for follow sub4sub", "review", "spam_promo", 2),
    ("SMK9003", "demo_karim", "Send 50 to my wallet and I double it", "hide", "spam_scam", 3),
    ("SMK9004", "demo_sara", "What time do you open on Fridays?", "review", "none", 0),
    ("SMK9005", "demo_noor", "Love this bakery, best croissants", "keep", "none", 0),
]


def seed(email: str) -> dict:
    db.execute(
        "insert into members (email, role) values (lower(%s), 'admin') "
        "on conflict (email) do update set role='admin', active=true",
        (email,))
    db.execute(
        "insert into accounts (username, display_name) values (%s, %s) "
        "on conflict (username) do nothing",
        (ACCOUNT, "Demo Bakery"))
    acc = db.fetch_one("select id from accounts where username=%s", (ACCOUNT,))
    db.execute(
        "insert into posts (code, account_id, status, caption) values (%s, %s, 'registered', %s) "
        "on conflict (code) do nothing",
        (POST, acc["id"], "Smoke-test post (synthetic seed)"))
    db.execute(
        "insert into uploads (source, filename, sha256, post_code, status, rows_total, "
        "  rows_inserted, finished_at) "
        "values ('generic_comments_csv', 'SMK-seed.csv', %s, %s, 'done', %s, %s, now()) "
        "on conflict (sha256) do nothing",
        ("smk-seed-v1", POST, SHEET_N_NEW, SHEET_N_NEW))
    up = db.fetch_one("select id from uploads where sha256=%s", ("smk-seed-v1",))
    db.execute(
        "insert into review_sheets (post_code, upload_id, n_new, n_flagged, status, ready_at) "
        "values (%s, %s, %s, %s, 'ready', now()) "
        "on conflict (upload_id, post_code) do nothing",
        (POST, up["id"], SHEET_N_NEW, SHEET_N_FLAGGED))
    for ig_id, author, text, verdict, category, severity in SEED_COMMENTS:
        db.execute(
            "insert into comments (ig_id, post_code, author, text, verdict, category, "
            "  severity, judge_reason, first_upload_id, last_upload_id) "
            "values (%s, %s, %s, %s, %s, %s, %s, 'smoke seed', %s, %s) "
            "on conflict (ig_id) do nothing",
            (ig_id, POST, author, text, verdict, category, severity, up["id"], up["id"]))
    sheet = db.fetch_one(
        "select id from review_sheets where post_code=%s", (POST,))
    queued = db.fetch_one(
        "select count(*) n from comments where verdict in ('hide','review') "
        "and decision is null and post_code=%s", (POST,))
    rows = db.fetch_one(
        "select coalesce(jsonb_array_length(sheet_comments(%s)), 0) n", (sheet["id"],))
    return {"member": email, "post": POST, "queued": queued["n"], "sheet_rows": rows["n"]}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="seed_smoke")
    p.add_argument("--email", default="smoke@example.com")
    args = p.parse_args(argv)
    print(seed(args.email))


if __name__ == "__main__":
    main()
