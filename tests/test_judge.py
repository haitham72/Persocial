from __future__ import annotations

import pytest

pytestmark = pytest.mark.db  # needs local Supabase; CI job 1 deselects with -m 'not db'

import random

from persocial import db
from persocial.bootstrap import ensure_defaults
from persocial.ingest.service import ingest_file
from persocial.judge import client, runner
from persocial.judge.select import draw_audit, group, select
from persocial.judge.taxonomy import apply_policy
from tests.conftest import EMO_ANGER, SENT_NEG, SENT_POS, TEST_ACCOUNT, comments_csv, raw_row


def _row(i, text, sent=SENT_POS, emo="[]"):
    return raw_row(i, text=text, sentiment_fast=sent, emotions_fast=emo,
                   updated_at="2026-06-04 11:39:30 UTC")


def test_policy():
    assert apply_policy("keep", "insult", 3) == ("hide", False)
    assert apply_policy("keep", "political_criticism", 2) == ("review", False)
    assert apply_policy("keep", "welfare", 1) == ("review", True)
    assert apply_policy("keep", "grief", 0) == ("keep", False)


def test_selection_rules_audit_and_dedup():
    rows = [
        {"ig_id": "1", "text": "you are a disgrace", "sentiment": "negative", "sentiment_score": .9},
        {"ig_id": "2", "text": "you are a disgrace", "sentiment": "negative", "sentiment_score": .9},
        {"ig_id": "3", "text": "❤️❤️", "sentiment": "negative", "sentiment_score": .7},
        {"ig_id": "4", "text": "DM me on whatsapp +1-555-0100", "sentiment": "neutral"},
        {"ig_id": "5", "text": "MashAllah", "sentiment": "negative", "sentiment_score": .4},
    ] + [{"ig_id": str(10 + i), "text": f"lovely view {i}", "sentiment": "positive"}
         for i in range(20)] + [{"ig_id": "50", "text": "ما أجمل المكان", "sentiment": "positive"}]
    from persocial.judge.rules import LexTerm
    from persocial.text import normalize, script_of
    for r in rows:
        r.update(text_norm=normalize(r["text"]), script=script_of(r["text"]))
        r.setdefault("emotion", None)
    lex = [LexTerm("whatsapp", "promo", False), LexTerm(normalize("mashallah"), "allow", False)]
    sel = select(rows, lex)
    cand = {it.ig_id: it.signals for it in sel.candidates}
    assert set(cand) == {"1", "2", "4"}                       # emoji + allow-listed skipped
    assert "lex:promo" in cand["4"] and "rule:phone" in cand["4"]
    assert len(group(sel.candidates)[normalize("you are a disgrace")]) == 2
    pool_before = len(sel.pool)
    drawn = draw_audit(sel.pool, 3, random.Random(7), 1)
    assert "50" in {it.ig_id for it in drawn}                  # Arabic stratum always sampled
    assert len(sel.pool) == pool_before - len(drawn)           # draws come out of the pool
    assert all(it.selection == "audit" and it.signals == ["audit:r1"] for it in drawn)


def test_review_run_end_to_end(monkeypatch):
    ensure_defaults()
    calls = []

    def fake_batch(model_row, prompt, items, account, caption):
        calls.append(items)
        bad = lambda t: "idiot" in t
        v = {rid: {"verdict": "hide" if bad(t) else "keep",
                   "category": "insult" if bad(t) else "none", "severity": 3 if bad(t) else 0,
                   "confidence": .9, "reason": "test"} for rid, t in items}
        return client.BatchResult(v, [client.CallRecord({"messages": []}, "{}", "ok", 5)])

    monkeypatch.setattr(client, "judge_batch", fake_batch)
    monkeypatch.setattr(client, "ensure_loaded", lambda _row: None)
    res = ingest_file("ZZT001-a.csv", comments_csv([
        _row(0, "you idiot", SENT_NEG, EMO_ANGER), _row(1, "you idiot", SENT_NEG),
        _row(2, "thanks for sharing", SENT_NEG), _row(3, "❤️"),
    ] + [_row(10 + i, f"great photo {i}") for i in range(10)]), account_hint=TEST_ACCOUNT)
    sheet_id = res.sheet_ids[0]
    run_id = runner.create_run(sheet_id=sheet_id, model_id="qwen3.5-9b",
                                   enqueue=False)
    out = runner.execute(run_id)
    assert out["judged"] == out["unique"]
    sent_texts = [t for batch in calls for _, t in batch]
    assert sent_texts.count("you idiot") == 1                  # duplicate judged once
    v = {r["ig_id"]: r for r in db.fetch_all(
        "select * from comments where judge_job_id=%s", (run_id,))}
    a, b = raw_row(0)["id"], raw_row(1)["id"]
    assert v[a]["verdict"] == v[b]["verdict"] == "hide" and v[b]["judged_as_copy_of"] == a
    assert v[a]["judge_model"] == "qwen3.5-9b" and v[a]["judged_at"] is not None
    assert raw_row(3)["id"] not in v                           # emoji-only never sent
    assert db.fetch_one("select count(*) n from judge_labels where job_id=%s", (run_id,))["n"] == len(v)
    sheet = db.fetch_one("select * from review_sheets where id=%s", (sheet_id,))
    assert sheet["status"] == "ready" and sheet["n_flagged"] == 2
    assert db.fetch_one("select count(*) n from notifications where sheet_id=%s",
                        (sheet_id,))["n"] == 1
    assert db.fetch_one("select count(*) n from judge_calls where job_id=%s", (run_id,))["n"] >= 1
    assert db.fetch_one("select n_flagged from posts where code='ZZT001'")["n_flagged"] == 2

    n_calls = len(calls)
    run2 = runner.create_run(sheet_id=sheet_id, model_id="qwen3.5-9b",
                                enqueue=False)  # same model+prompt: cached
    runner.execute(run2)
    resent = [t for batch in calls[n_calls:] for _, t in batch]
    assert "you idiot" not in resent and "thanks for sharing" not in resent  # only new audit draws


def _audit_run(monkeypatch, audit_flags: bool):
    """Post with 2 negatives + 40 neutral comments; the fake judge hides negatives and
    (optionally) everything in audit draws."""
    ensure_defaults()

    def fake_batch(model_row, prompt, items, account, caption):
        v = {}
        for rid, t in items:
            bad = "idiot" in t or (audit_flags and "neutral" in t)
            v[rid] = {"verdict": "hide" if bad else "keep", "category": "insult" if bad else "none",
                      "severity": 3 if bad else 0, "confidence": .9, "reason": "t"}
        return client.BatchResult(v, [client.CallRecord({"messages": []}, "{}", "ok", 1)])

    monkeypatch.setattr(client, "judge_batch", fake_batch)
    monkeypatch.setattr(client, "ensure_loaded", lambda _row: None)
    db.execute("update settings set value='2' where key='audit_min'")
    try:
        rows = [_row(0, "you idiot one", SENT_NEG), _row(1, "you idiot two", SENT_NEG)] + \
               [_row(10 + i, f"neutral remark number {i}") for i in range(40)]
        res = ingest_file("ZZT001-a.csv", comments_csv(rows), account_hint=TEST_ACCOUNT)
        run_id = runner.create_run(sheet_id=res.sheet_ids[0], enqueue=False)
        return runner.execute(run_id)
    finally:
        db.execute("update settings set value='5' where key='audit_min'")


def test_adaptive_audit_stops_when_audit_is_clean(monkeypatch):
    out = _audit_run(monkeypatch, audit_flags=False)
    assert out["candidates"] == 2
    assert len(out["audit_rounds"]) == 1                       # X=2 drawn, nothing found, stop
    assert out["audit_rounds"][0]["drawn"] == 2 and not out["audit_rounds"][0]["expand"]


def test_adaptive_audit_expands_while_nlp_is_missing(monkeypatch):
    out = _audit_run(monkeypatch, audit_flags=True)
    rounds = out["audit_rounds"]
    assert len(rounds) > 1 and all(r["expand"] for r in rounds)
    assert sum(r["drawn"] for r in rounds) <= 21               # capped at 50% of 42 eligible


def test_dataset_export_uses_best_label(monkeypatch, tmp_path):
    """A human decision outranks the teacher's verdict in the training target."""
    import json as _json

    from persocial import dataset
    from persocial.config import settings
    ensure_defaults()

    def fake_batch(model_row, prompt, items, account, caption):
        v = {rid: {"verdict": "hide", "category": "insult", "severity": 3, "confidence": .9,
                   "reason": "t"} for rid, _ in items}
        return client.BatchResult(v, [client.CallRecord(
            {"messages": [{"role": "user", "content": "PAYLOAD"}]}, "{}", "ok", 1)])

    monkeypatch.setattr(client, "judge_batch", fake_batch)
    monkeypatch.setattr(client, "ensure_loaded", lambda _row: None)
    monkeypatch.setattr(settings(), "datasets_root", tmp_path)
    res = ingest_file("ZZT001-a.csv", comments_csv([_row(0, "you idiot", SENT_NEG),
                                                     _row(1, "you clown", SENT_NEG)]),
                      account_hint=TEST_ACCOUNT)
    job = runner.create_run(sheet_id=res.sheet_ids[0], enqueue=False)
    runner.execute(job)
    db.execute("update comments set decision='keep' where ig_id=%s", (raw_row(1)["id"],))
    out = dataset.export("zzt", eval_share=0)
    assert out["train"] >= 1
    rows = [_json.loads(l) for l in (tmp_path / "zzt" / "train.jsonl").read_text(encoding="utf-8").splitlines()]
    mine = [r for r in rows if r["meta"]["post"] == "ZZT001"]
    target = _json.loads(mine[0]["messages"][2]["content"])
    assert mine[0]["messages"][1]["content"] == "PAYLOAD"
    assert sorted(v[0] for v in target.values()) == ["hide", "keep"]     # human keep wins
    assert mine[0]["meta"]["tiers"] == {"single": 1, "human": 1}
def test_tiebreak_splits_shaky_hides(monkeypatch):
    """Primary hides under the confidence threshold get a second opinion: a split
    lands the comment in review tagged tiebreak:split, agreement stays hidden."""
    ensure_defaults()

    def fake_batch(model_row, prompt, items, account, caption):
        v = {}
        for rid, t in items:
            if model_row["id"] == "qwen3.5-4b":  # tiebreak model keeps everything
                v[rid] = {"verdict": "keep", "category": "none", "severity": 0,
                          "confidence": .9, "reason": "second look"}
            else:                                # shaky primary hides everything
                v[rid] = {"verdict": "hide", "category": "insult", "severity": 3,
                          "confidence": .5, "reason": "shaky"}
        return client.BatchResult(v, [client.CallRecord({"messages": []}, "{}", "ok", 1)])

    monkeypatch.setattr(client, "judge_batch", fake_batch)
    monkeypatch.setattr(client, "ensure_loaded", lambda _row: None)
    prev = db.fetch_one("select value from settings where key='tiebreak_model'")["value"]
    db.execute("update settings set value='qwen3.5-4b' where key='tiebreak_model'")
    try:
        res = ingest_file("ZZT001-a.csv", comments_csv([
            _row(0, "you idiot", SENT_NEG), _row(1, "plainly fine", SENT_POS),
        ]), account_hint=TEST_ACCOUNT)
        run_id = runner.create_run(sheet_id=res.sheet_ids[0], model_id="qwen3.5-9b",
                                   enqueue=False)
        out = runner.execute(run_id)
        assert out["tiebreak"] == 2 and out["tiebreak_agree"] == 0  # candidate + audit hide
        c = db.fetch_one("select verdict, judge_reason from comments where ig_id=%s",
                         (raw_row(0)["id"],))
        assert c["verdict"] == "review" and c["judge_reason"].startswith("tiebreak:split")
        job = db.fetch_one("select n_tiebreak, tiebreak_agree from jobs where id=%s", (run_id,))
        assert (job["n_tiebreak"], job["tiebreak_agree"]) == (2, 0)
        assert db.fetch_one("select count(*) n from judge_labels where job_id=%s "
                            "and model='qwen3.5-4b'", (run_id,))["n"] == 2
    finally:
        db.execute("update settings set value=%s where key='tiebreak_model'", (prev,))
def _autohide_run(monkeypatch, mode):
    ensure_defaults()

    def fake_batch(model_row, prompt, items, account, caption):
        v = {rid: {"verdict": "hide", "category": "insult", "severity": 3,
                   "confidence": .95, "reason": "certain"} for rid, _ in items}
        return client.BatchResult(v, [client.CallRecord({"messages": []}, "{}", "ok", 1)])

    monkeypatch.setattr(client, "judge_batch", fake_batch)
    monkeypatch.setattr(client, "ensure_loaded", lambda _row: None)
    prev = db.fetch_one("select value from settings where key='autohide_mode'")["value"]
    db.execute("update settings set value=%s where key='autohide_mode'", (mode,))
    try:
        res = ingest_file("ZZT001-a.csv", comments_csv([_row(0, "you idiot", SENT_NEG)]),
                          account_hint=TEST_ACCOUNT)
        run_id = runner.create_run(sheet_id=res.sheet_ids[0], model_id="qwen3.5-9b",
                                   enqueue=False)
        return run_id, runner.execute(run_id)
    finally:
        db.execute("update settings set value=%s where key='autohide_mode'", (prev,))


def test_autohide_shadow_records_without_deciding(monkeypatch):
    run_id, out = _autohide_run(monkeypatch, "shadow")
    assert out["autohide"] == 1
    r = db.fetch_one("select mode from auto_actions where job_id=%s", (run_id,))
    assert r["mode"] == "shadow"
    c = db.fetch_one("select decision from comments where ig_id=%s", (raw_row(0)["id"],))
    assert c["decision"] is None


def test_autohide_live_stamps_decision(monkeypatch):
    _run_id, out = _autohide_run(monkeypatch, "live")
    assert out["autohide"] == 1
    c = db.fetch_one("select decision, decision_note from comments where ig_id=%s",
                     (raw_row(0)["id"],))
    assert c["decision"] == "hide" and c["decision_note"].startswith("auto-hide rule")
