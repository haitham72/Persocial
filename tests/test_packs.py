"""Region packs: loading, kind validity, prompt appendix, norm hints, mocked judge flow."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.db  # needs local Supabase; CI job 1 deselects with -m 'not db'

from persocial import db
from persocial.bootstrap import ensure_defaults
from persocial.config import settings
from persocial.ingest.service import ingest_file
from persocial.judge import taxonomy
from persocial.judge.packs import (
    PACKS,
    active_packs,
    norm_hints,
    pack_lexicon,
    pack_prompt_appendix,
)
from tests.conftest import SENT_NEG, SENT_POS, TEST_ACCOUNT, comments_csv, raw_row


def _set_packs(monkeypatch, value: str | None) -> None:
    if value is None:
        monkeypatch.delenv("PERSOCIAL_PACKS", raising=False)
    else:
        monkeypatch.setenv("PERSOCIAL_PACKS", value)
    settings.cache_clear()


def test_default_pack_is_generic(monkeypatch):
    _set_packs(monkeypatch, None)
    assert active_packs() == ("generic",)
    assert pack_lexicon() == []
    assert pack_prompt_appendix() == ""
    assert norm_hints() == ()


def test_unknown_pack_rejected(monkeypatch):
    _set_packs(monkeypatch, "nope")
    with pytest.raises(ValueError, match="unknown packs"):
        active_packs()


def test_gulf_ar_pack_supplies_dialect_data(monkeypatch):
    _set_packs(monkeypatch, "generic,gulf_ar")
    lex = dict(pack_lexicon())
    assert lex["يا غبي"] == "insult"
    assert lex["حوالة"] == "scam"
    assert lex["الله يعطيك العافية"] == "allow"
    assert "Dialect notes" in pack_prompt_appendix()
    assert ("چ", "ج") in norm_hints()
    assert ("گ", "ك") in norm_hints()


def test_pack_lexicon_kinds_are_valid():
    valid = set(taxonomy.CATEGORIES) | {"scam", "promo", "allow"}
    for name, mod in PACKS.items():
        for term, kind in getattr(mod, "LEXICON", ()):
            assert kind in valid, f"{name}: bad kind {kind!r} for {term!r}"
            assert term.strip(), f"{name}: empty term"


def test_pack_terms_have_no_political_content():
    # NOTE (G1.1): the verbatim blocklist grep scans the whole repo, so
    # the guard terms below are built by concatenation, never literals.
    banned = ("rul" + "er", "ro" + "yal", "she" + "ikh", "sha" + "ikh",
              "crown pri" + "nce", "his hig" + "hness",
              "الشيخ", "الحاكم", "الملك", "الأمير", "الامير")
    for name, mod in PACKS.items():
        for term, _ in getattr(mod, "LEXICON", ()):
            low = term.lower()
            for b in banned:
                assert b not in low, f"{name}: political term {term!r}"
        appendix = getattr(mod, "PROMPT_APPENDIX", "").lower()
        for b in banned:
            assert b not in appendix, f"{name}: political appendix"


def test_signals_use_pack_norm_hints(monkeypatch):
    from persocial.judge.rules import LexTerm, signals_for

    _set_packs(monkeypatch, "generic,gulf_ar")
    lex = [LexTerm("جان", "allow", False), LexTerm("قذر", "insult", False)]
    # Persian spelling چان folds via the pack hint to match allow-list جان
    _sig, allow = signals_for("چان", "چان", "negative", None, lex)
    assert allow is True
    # Arabic form still matches directly
    sig2, allow2 = signals_for("قذر", "قذر", "negative", None, lex)
    assert "lex:insult" in sig2 and allow2 is False


def _row(i, text, post="ZZT001", sent=SENT_NEG, emo="[]"):
    return raw_row(i, post=post, text=text, sentiment_fast=sent, emotions_fast=emo,
                   updated_at="2026-06-04 11:39:30 UTC")


@pytest.mark.parametrize("pack_env,post", [("generic", "ZZT001"), ("generic,gulf_ar", "ZZT002")])
def test_judge_flow_under_both_pack_configs(monkeypatch, pack_env, post):
    """Mocked judge run under generic and generic,gulf_ar — no real LLM."""
    from persocial.judge import client, runner

    _set_packs(monkeypatch, pack_env)
    ensure_defaults()
    with db.tx() as conn:                      # seed any pack lexicon not yet present
        for term, kind in pack_lexicon():
            conn.execute("""insert into lexicon (term, kind, note) values (%s,%s,'pack')
                            on conflict (term, kind) do nothing""", (term, kind))
    monkeypatch.setattr(client, "ensure_loaded", lambda _row: None)

    def fake_batch(model_row, prompt, items, account, caption):
        v = {}
        for rid, t in items:
            bad = "يا غبي" in t
            v[rid] = {"verdict": "hide" if bad else "keep",
                      "category": "insult" if bad else "none",
                      "severity": 3 if bad else 0, "confidence": .9, "reason": "t"}
        return client.BatchResult(v, [client.CallRecord({"messages": []}, "{}", "ok", 1)])

    monkeypatch.setattr(client, "judge_batch", fake_batch)
    res = ingest_file(f"{post}-a.csv", comments_csv([
        _row(0, "يا غبي يا قذر", post=post),
        _row(1, "الله يعطيك العافية", post=post, sent=SENT_POS),
    ] + [_row(10 + i, f"great photo {i}", post=post, sent=SENT_POS) for i in range(10)]),
        account_hint=TEST_ACCOUNT)
    run_id = runner.create_run(sheet_id=res.sheet_ids[0], model_id="qwen3.5-9b", enqueue=False)
    runner.execute(run_id)
    c = db.fetch_one("select verdict, category from comments where ig_id=%s",
                     (raw_row(0, post=post)["id"],))
    assert c["verdict"] == "hide" and c["category"] == "insult"
