from __future__ import annotations

import pytest

pytestmark = pytest.mark.db  # needs local Supabase; CI job 1 deselects with -m 'not db'

import csv
import io

from persocial import db
from persocial.ingest.service import ingest_file
from persocial.scoring import claims
from tests.conftest import SENT_NEG, TEST_ACCOUNT, comments_csv, raw_row


def _score(rows):
    return [{"ig_id": r["ig_id"], "sentiment": [{"label": "negative", "score": 0.9},
             {"label": "neutral", "score": 0.07}, {"label": "positive", "score": 0.03}],
             "emotions": [{"label": "anger", "score": 0.6}]} for r in rows]


def test_lease_save_points_and_release():
    res = ingest_file("ZZT001-a.csv", comments_csv([raw_row(i) for i in range(5)]),
                      account_hint=TEST_ACCOUNT)
    [lease] = claims.claim(1, "colab:test", ["ZZT001"])
    assert lease["post_code"] == "ZZT001" and lease["n_unscored"] == 5
    assert claims.claim(1, "other", ["ZZT001"]) == []            # leased: nobody else gets it
    first = claims.comments("ZZT001", 2)
    out = claims.submit("ZZT001", _score(first), "colab:test")   # save point 1
    assert out == {"written": 2, "remaining": 3}
    post = db.fetch_one("select claimed_by, n_scored from posts where code='ZZT001'")
    assert post["claimed_by"] == "colab:test" and post["n_scored"] == 2
    out = claims.submit("ZZT001", _score(claims.comments("ZZT001", 100)), "colab:test")
    assert out["remaining"] == 0
    post = db.fetch_one("select claimed_by, n_scored, n_negative from posts where code='ZZT001'")
    assert post["claimed_by"] is None and post["n_scored"] == 5 and post["n_negative"] == 5
    c = db.fetch_one("select sentiment, sent_negative, emotion, scored_by from comments where ig_id=%s",
                     (raw_row(0)["id"],))
    assert c == {"sentiment": "negative", "sent_negative": 0.9, "emotion": "anger", "scored_by": "colab:test"}
    assert db.fetch_one("select status from review_sheets where id=%s",
                        (res.sheet_ids[0],))["status"] == "ready"


def test_expired_lease_is_reclaimable_and_csv_round_trip():
    ingest_file("ZZT001-a.csv", comments_csv([raw_row(i) for i in range(3)]), account_hint=TEST_ACCOUNT)
    claims.claim(1, "dead-colab", ["ZZT001"])
    db.execute("update posts set claim_expires_at = now() - interval '1 minute' where code='ZZT001'")
    [again] = claims.claim(1, "fresh", ["ZZT001"])
    assert again["post_code"] == "ZZT001"
    exported = claims.csv_bytes("ZZT001")
    assert b"01/02/2025, 10:00:00" in exported                    # UTC, day-first round-trip
    rows = list(csv.DictReader(io.StringIO(exported.decode())))
    for r in rows:
        r.update(sentiment_fast=SENT_NEG, emotions_fast="[]", updated_at="2026-10-19 10:00:00 UTC")
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0]) )
    w.writeheader(); w.writerows(rows)
    back = ingest_file("ZZT001-comment--3-scored.csv", buf.getvalue().encode())
    assert back.rows_inserted == 0 and back.rows_scored == 3
    assert db.fetch_one("select claimed_by from posts where code='ZZT001'")["claimed_by"] is None
