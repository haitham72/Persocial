"""Tier 1 headless path: store dedup, NLP triage, judge fan-out, report outputs.

No torch, no network, no Supabase: scoring is faked, judge_batch is stubbed.
"""

from __future__ import annotations

import csv
import sqlite3

import pytest

from persocial.judge import client
from persocial.local import lexicon as lex_mod
from persocial.local import report as report_mod
from persocial.local import run as run_mod
from persocial.local import store as store_mod


class FakeScorer:
    def __init__(self, device="cpu", batch_size=0):
        self.batch_size = 64
        self.runner = "cpu:test"

    def score(self, texts):
        out = []
        for t in texts:
            if "scam" in t or "hate" in t:
                out.append(([{"label": "negative", "score": 0.9},
                             {"label": "neutral", "score": 0.07},
                             {"label": "positive", "score": 0.03}], []))
            else:
                out.append(([{"label": "positive", "score": 0.9},
                             {"label": "neutral", "score": 0.07},
                             {"label": "negative", "score": 0.03}], []))
        return out


@pytest.fixture
def cwd_store(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("persocial.scoring.core.Scorer", FakeScorer)
    return tmp_path


def _seed(store: store_mod.Store) -> None:
    from persocial.ingest.parsers import parse_generic_comments

    rows = [
        {"text": "earn money fast with this crypto scam", "comment_id": "90001",
         "post_id": "DBK001", "username": "demo_a"},
        {"text": "earn money fast with this crypto scam", "comment_id": "90002",
         "post_id": "DBK001", "username": "demo_b"},
        {"text": "I hate this place, terrible service", "comment_id": "90003",
         "post_id": "DBK001", "username": "demo_c"},
        {"text": "love this bakery, best croissants", "comment_id": "90004",
         "post_id": "DBK002", "username": "demo_d"},
        {"text": "❤️❤️❤️", "comment_id": "90005",
         "post_id": "DBK002", "username": "demo_e"},
    ]
    parsed = parse_generic_comments("generic.csv", rows)
    assert not parsed.rejects
    return store.upsert_parsed(parsed, "generic.csv", "digest-1")


def test_upsert_dedups_on_rerun(cwd_store):
    store = store_mod.Store()
    try:
        first = _seed(store)
        assert first == {"inserted": 5, "existing": 0}
        second = _seed(store)
        assert second == {"inserted": 0, "existing": 5}
        assert store.stats()["comments"] == 5
    finally:
        store.close()


def test_nlp_triage_marks_scam_and_keeps_praise(cwd_store):
    store = store_mod.Store()
    try:
        _seed(store)
        run_mod.ensure_scored(store, device="cpu")
        lex = lex_mod.build_lexicon(("generic", "gulf_ar"))
        tri = run_mod.triage_nlp(store, lex)
        assert tri["candidates"] >= 2  # scam x2 (dup text) + hate
        rows = {c["ig_id"]: c for c in store.all_comments()}
        assert rows["90001"]["verdict"] == "hide"
        assert rows["90001"]["category"] == "spam_scam"
        assert rows["90002"]["verdict"] == "hide"  # duplicate text judged too
        assert rows["90004"]["verdict"] == "keep"  # pool or audit sample, still keep
        assert store.stats()["judged"] == 5  # emoji-only row kept via skip-close
    finally:
        store.close()


def test_judge_items_fans_out_and_applies_policy(cwd_store, monkeypatch):
    from persocial.judge.select import Item

    def fake_batch(model_row, prompt, items, account, caption):
        verdicts = {}
        for rid, text in items:
            if "scam" in text:
                verdicts[rid] = {"verdict": "hide", "category": "spam_scam",
                                 "severity": 3, "confidence": 0.9, "reason": "stub"}
            else:
                verdicts[rid] = {"verdict": "keep", "category": "none",
                                 "severity": 0, "confidence": 0.9, "reason": "stub"}
        return client.BatchResult(verdicts, [])

    monkeypatch.setattr(client, "judge_batch", fake_batch)
    store = store_mod.Store()
    try:
        _seed(store)
        items = [Item("90001", "earn money fast with this crypto scam",
                      "earn money fast with this crypto scam", "latin",
                      "negative", 0.9, None, "DBK001"),
                 Item("90002", "earn money fast with this crypto scam",
                      "earn money fast with this crypto scam", "latin",
                      "negative", 0.9, None, "DBK001")]
        for it in items:
            it.selection = "candidate"
            it.signals = ["lex:scam"]
        flagged = run_mod.judge_items(store, items, run_mod._judge_model_row("stub"),
                                      "prompt")
        assert flagged == 2
        rows = {c["ig_id"]: c for c in store.all_comments()}
        assert rows["90001"]["verdict"] == "hide"
        assert rows["90002"]["verdict"] == "hide"
    finally:
        store.close()


def test_reports_open_with_all_sheets(cwd_store):
    store = store_mod.Store()
    try:
        _seed(store)
        run_mod.ensure_scored(store, device="cpu")
        run_mod.triage_nlp(store, lex_mod.build_lexicon(("generic", "gulf_ar")))
        rows = store.all_comments()
        base = cwd_store / "triage"
        report_mod.write_xlsx(base.with_suffix(".xlsx"), rows, {"judge": "nlp-only"})
        report_mod.write_csv(base.with_suffix(".csv"), rows)
        report_mod.write_html(base.with_suffix(".html"), rows, {"judge": "nlp-only"})
    finally:
        store.close()
    from openpyxl import load_workbook

    wb = load_workbook(cwd_store / "triage.xlsx")
    assert set(wb.sheetnames) == {"To review", "Hidden-suggested", "Keep", "Audit",
                                  "Summary"}
    hidden = list(wb["Hidden-suggested"].values)[1:]
    assert len(hidden) == 2  # both duplicate scam comments
    with open(cwd_store / "triage.csv", encoding="utf-8") as f:
        assert next(csv.reader(f)) == report_mod.COLUMNS
    html = (cwd_store / "triage.html").read_text(encoding="utf-8")
    assert "f-verdict" in html and "f-category" in html and "f-language" in html
    assert "instagram.com/p/DBK001" in html


def test_run_end_to_end_incremental(cwd_store, tmp_path):
    src = tmp_path / "in.csv"
    src.write_text("text,comment_id,post_id,username\n"
                   "love this bakery,90011,DBK009,demo_x\n"
                   "earn money crypto scam,90012,DBK009,demo_y\n", encoding="utf-8")
    out1 = run_mod.run(str(src), out=str(cwd_store / "t1"), no_judge=True, device="cpu")
    assert out1["inserted"] == 2 and out1["judged"] == 2
    out2 = run_mod.run(str(src), out=str(cwd_store / "t2"), no_judge=True, device="cpu")
    assert out2["inserted"] == 0 and out2["existing"] == 2
    assert (cwd_store / "t1.xlsx").exists()
    assert (cwd_store / "t1.csv").exists()
    assert (cwd_store / "t1.html").exists()


def test_unknown_pack_rejected():
    with pytest.raises(ValueError):
        lex_mod.resolve_packs(("nope",))


def test_instagram_link_shapes():
    assert report_mod.instagram_link("ABC123", "90001") == \
        "https://www.instagram.com/p/ABC123/c/90001/"
    assert report_mod.instagram_link("ABC123", "sha1abc") == \
        "https://www.instagram.com/p/ABC123/"


def test_store_is_sqlite_file(cwd_store):
    store = store_mod.Store()
    try:
        _seed(store)
    finally:
        store.close()
    con = sqlite3.connect(cwd_store / ".persocial" / "persocial.db")
    assert con.execute("select count(*) from comments").fetchone()[0] == 5
    con.close()
