"""Shared fixtures for the pytest suite.

DB tests (marked `db`) run against the local Supabase database (`supabase start`).
Everything they create uses the ZZT post-code prefix and the zz_test account, and is
deleted after each test, so they're safe to run next to real data. Text is synthetic —
no corpus rows.

Pure tests (no `db` mark: test_local, test_adapters, test_golden, test_judge_parse,
test_notebook) never touch the database, so CI job 1 runs them with no Supabase.
"""

from __future__ import annotations

import csv
import io
import os

os.environ.setdefault("AUTO_JUDGE", "false")
os.environ.setdefault("AUTO_SCORE_LOCAL", "false")

import pytest

TEST_ACCOUNT = "zz_test"


def _cleanup():
    from persocial import db

    with db.tx() as conn:
        conn.execute("delete from jobs where post_code like 'ZZT%%'")
        conn.execute("delete from judge_calls where post_code like 'ZZT%%'")
        conn.execute("delete from notifications where post_code like 'ZZT%%'")
        conn.execute("delete from posts where code like 'ZZT%%'")
        conn.execute("delete from uploads where filename like 'ZZT%%'")
        conn.execute("delete from accounts where username = %s", (TEST_ACCOUNT,))


@pytest.fixture(autouse=True)
def clean_db(request):
    """auto_judge lives in settings (read by the SQL sheet logic): off during tests so
    fully-scored sheets go straight to 'ready', restored afterwards. Pure (non-db)
    tests yield immediately so they run with no database at all."""
    if "db" not in request.keywords:
        yield
        return
    from persocial import db

    prev = db.fetch_one("select value from settings where key='auto_judge'")
    db.execute("update settings set value='false' where key='auto_judge'")
    _cleanup()
    yield
    _cleanup()
    db.execute("update settings set value=%s where key='auto_judge'",
               (prev["value"] if prev else "true",))


COMMENT_HEADER = ["id", "owner_id", "username", "text", "created_at", "postID",
                  "comment_number", "sentiment_fast", "emotions_fast", "updated_at",
                  "profile_url", "profile_pic_url", "Spam"]


def comments_csv(rows: list[dict], header: list[str] = COMMENT_HEADER) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=header, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in header})
    return buf.getvalue().encode("utf-8")


def raw_row(i: int, post: str = "ZZT001", text: str | None = None, **kw) -> dict:
    return {"id": str(9_000_000_000 + i), "owner_id": str(100 + i), "username": f"user{i}",
            "text": text or f"synthetic comment {i}", "created_at": "01/02/2025, 10:00:00",
            "postID": post, "comment_number": "50.0", **kw}


SENT_NEG = '[{"label": "negative", "score": 0.91}, {"label": "neutral", "score": 0.06}, {"label": "positive", "score": 0.03}]'
SENT_POS = '[{"label": "positive", "score": 0.95}, {"label": "neutral", "score": 0.04}, {"label": "negative", "score": 0.01}]'
EMO_ANGER = '[{"label": "anger", "score": 0.71}]'
