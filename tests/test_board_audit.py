"""WP7: team board columns + comment audit log, against the squashed schema."""
from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.db  # needs local Supabase; CI job 1 deselects with -m 'not db'

from persocial import db
from tests.conftest import TEST_ACCOUNT


def _seed(post="ZZT900", n=2):
    db.execute(
        "insert into accounts (username) values (%s) on conflict (username) do nothing",
        (TEST_ACCOUNT,))
    acc = db.fetch_one("select id from accounts where username=%s", (TEST_ACCOUNT,))
    db.execute(
        "insert into posts (code, account_id, status) values (%s, %s, 'registered') "
        "on conflict (code) do nothing", (post, acc["id"]))
    ids = []
    for i in range(n):
        ig = f"ZZT900{i}"
        db.execute(
            "insert into comments (ig_id, post_code, author, text, verdict) values "
            "(%s, %s, %s, %s, 'review') on conflict (ig_id) do nothing",
            (ig, post, "zz_author", f"needs review {i}"))
        ids.append(ig)
    return ids


def _events(ig):
    return db.fetch_all(
        "select action, actor, from_value, to_value from comment_events "
        "where comment_id=%s order by id", (ig,))


def test_board_columns_default_new():
    (ig,) = _seed()[:1]
    row = db.fetch_one("select status, assignee from comments where ig_id=%s", (ig,))
    assert row["status"] == "new"
    assert row["assignee"] is None


def test_board_status_transitions():
    (ig,) = _seed()[:1]
    for s in ("assigned", "in_review", "done"):
        db.execute("update comments set status=%s where ig_id=%s", (s, ig))
        assert db.fetch_one("select status from comments where ig_id=%s",
                            (ig,))["status"] == s


def test_board_status_rejects_unknown():
    (ig,) = _seed()[:1]
    with pytest.raises(Exception, match="comments_status_check"):
        db.execute("update comments set status='archived' where ig_id=%s", (ig,))


def test_audit_logs_decision_assignee_status():
    (ig,) = _seed()[:1]
    who = uuid.uuid4()
    db.execute("update comments set decision='hide' where ig_id=%s", (ig,))
    db.execute("update comments set assignee=%s where ig_id=%s", (str(who), ig))
    db.execute("update comments set status='in_review' where ig_id=%s", (ig,))
    got = {(e["action"], e["from_value"], e["to_value"]) for e in _events(ig)}
    assert ("decision", None, "hide") in got
    assert ("assignee", None, str(who)) in got
    assert ("status", "new", "in_review") in got
    actors = {e["actor"] for e in _events(ig)}
    assert actors == {"system"}  # direct DB session: no JWT, falls back like the stamp


def test_audit_ignores_non_reviewed_columns():
    (ig,) = _seed()[:1]
    db.execute("update comments set text='edited text' where ig_id=%s", (ig,))
    assert _events(ig) == []
    db.execute("update comments set decision='keep' where ig_id=%s", (ig,))
    db.execute("update comments set decision='keep' where ig_id=%s", (ig,))
    assert len(_events(ig)) == 1  # same-value update logs nothing
