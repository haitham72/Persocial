from __future__ import annotations

from datetime import timedelta

import pytest

pytestmark = pytest.mark.db  # needs local Supabase; CI job 1 deselects with -m 'not db'

from persocial import db
from persocial.ingest.dates import parse_local
from persocial.ingest.service import UnknownPostsError, ingest_file
from persocial.text import normalize, script_of
from tests.conftest import EMO_ANGER, SENT_NEG, SENT_POS, TEST_ACCOUNT, comments_csv, raw_row


def test_dates_are_day_first_local():
    d = parse_local("01/02/2025, 10:00:00")
    assert (d.year, d.month, d.day, d.hour) == (2025, 2, 1, 10)
    assert d.utcoffset() == timedelta(0)
    assert parse_local("2026-06-04 11:39:30 UTC").utcoffset() == timedelta(0)


def test_normalize_arabic_forms_collapse():
    assert normalize("اللــــه") == normalize("ٱللَّه") == normalize("الله")
    assert normalize("سلاااام @someone http://x.y") == "سلاام @user <url>"
    assert script_of("❤️❤️") == "emoji"
    assert script_of("hello مرحبا") == "mixed"


def test_raw_upload_creates_comments_and_sheet():
    res = ingest_file("ZZT001-comment--50.csv", comments_csv([raw_row(i) for i in range(5)]),
                      account_hint=TEST_ACCOUNT)
    assert (res.rows_inserted, res.rows_updated, res.rows_scored) == (5, 0, 0)
    assert len(res.sheet_ids) == 1
    sheet = db.fetch_one("select * from review_sheets where id=%s", (res.sheet_ids[0],))
    assert sheet["n_new"] == 5 and sheet["status"] == "scoring"


def test_same_file_twice_writes_nothing():
    data = comments_csv([raw_row(i) for i in range(3)])
    ingest_file("ZZT001-a.csv", data, account_hint=TEST_ACCOUNT)
    again = ingest_file("ZZT001-a.csv", data)
    assert again.duplicate_file
    assert db.fetch_one("select count(*) n from comments where post_code='ZZT001'")["n"] == 3


def test_overlap_only_inserts_new_and_sheet_has_only_new():
    ingest_file("ZZT001-a.csv", comments_csv([raw_row(i) for i in range(3)]),
                account_hint=TEST_ACCOUNT)
    res = ingest_file("ZZT001-b.csv", comments_csv([raw_row(i) for i in range(1, 6)]))
    assert (res.rows_inserted, res.rows_updated) == (3, 2)
    sheet = db.fetch_one("select n_new from review_sheets where id=%s", (res.sheet_ids[0],))
    assert sheet["n_new"] == 3


def test_scored_upload_and_scores_are_never_overwritten():
    rows = [raw_row(0, sentiment_fast=SENT_NEG, emotions_fast=EMO_ANGER,
                    updated_at="2026-06-04 11:39:30 UTC"),
            raw_row(1, sentiment_fast=SENT_POS, emotions_fast="[]",
                    updated_at="2026-06-04 11:39:30 UTC")]
    res = ingest_file("ZZT001-s.csv", comments_csv(rows), account_hint=TEST_ACCOUNT)
    assert res.rows_scored == 2
    s = db.fetch_one("select emotion, scored_at from comments where ig_id=%s", (raw_row(1)["id"],))
    assert s["emotion"] is None and s["scored_at"] is not None   # [] = nothing above threshold
    rows[0]["sentiment_fast"] = SENT_POS               # different bytes, conflicting score
    ingest_file("ZZT001-s2.csv", comments_csv(rows))
    s = db.fetch_one("select sentiment, sent_negative from comments where ig_id=%s", (raw_row(0)["id"],))
    assert s["sentiment"] == "negative" and abs(s["sent_negative"] - 0.91) < 1e-4
    sheet = db.fetch_one("select status from review_sheets where id=%s", (res.sheet_ids[0],))
    assert sheet["status"] == "ready"                  # fully scored, AUTO_JUDGE off in tests


def test_bad_rows_rejected_and_unknown_post_needs_account():
    rows = [raw_row(0), {**raw_row(1), "id": ""}]
    with pytest.raises(UnknownPostsError):
        ingest_file("ZZT002-x.csv", comments_csv([raw_row(0, post="ZZT002")]))
    res = ingest_file("ZZT001-r.csv", comments_csv(rows), account_hint=TEST_ACCOUNT)
    assert res.rows_inserted == 1 and res.rows_rejected == 1


def test_post_id_from_filename_when_column_missing():
    header = ["id", "owner_id", "username", "text", "created_at", "Spam"]
    res = ingest_file("ZZT003-comment--7.csv", comments_csv([raw_row(0)], header=header),
                      account_hint=TEST_ACCOUNT)
    assert res.posts == ["ZZT003"]


METRIC_HEADER = ["Code", "username", "caption_text", "carousel_media", "comment_count",
                 "created_at", "engagement_rate", "img_small", "like_count", "play_count",
                 "user_follower_count", "video_url"]


def _metrics(likes: int, comments: int) -> bytes:
    return comments_csv([{"Code": "ZZT010", "username": TEST_ACCOUNT, "caption_text": "cap",
                          "comment_count": str(comments), "created_at": "2026-06-06",
                          "like_count": str(likes), "play_count": "10",
                          "user_follower_count": "1000"}], header=METRIC_HEADER)


def test_metrics_snapshots_and_latest_only_moves_forward():
    ingest_file("ZZT-zz_test-20260617-114742.csv", _metrics(100, 10))
    ingest_file("ZZT-zz_test-20260618-090000.csv", _metrics(250, 40))
    ingest_file("ZZT-zz_test-20260601-090000.csv", _metrics(5, 1))     # older, arrives late
    post = db.fetch_one("select public.post_grid(null, 'posted', 1, 'ZZT010') -> 0 as p")["p"]
    assert post["like_count"] == 250 and post["comment_count"] == 40
    assert post["like_delta"] == 150 and post["comment_delta"] == 30
    n = db.fetch_one("select count(*) n from post_snapshots where post_code='ZZT010'")["n"]
    assert n == 3
    assert post["metrics_updated_at"]
