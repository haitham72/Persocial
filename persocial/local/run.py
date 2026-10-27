"""Tier 1 headless pipeline: parse -> SQLite store -> HF score -> select -> judge.

Reuses `Scorer`, `select`/`draw_audit`/`group`, `judge_batch` and `apply_policy`
unchanged; all Tier 2-isms (Postgres, jobs, sheets) are adapted at the store
boundary (`Store`). Re-runs are incremental: comments already scored or judged
are never re-processed.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

from persocial.config import settings
from persocial.judge import client
from persocial.judge.select import draw_audit, group, select
from persocial.judge.taxonomy import apply_policy
from persocial.local import doctor
from persocial.local import lexicon as lex_mod
from persocial.local import report as report_mod
from persocial.local import store as store_mod
from persocial.local.models import models_cached

# Signals that hide on NLP evidence alone (scam asks cost victims money).
_NLP_HIDE = {"lex:scam", "rule:wallet"}
# First matching signal decides the NLP-only category.
_NLP_CAT = (("lex:scam", "spam_scam"), ("rule:wallet", "spam_scam"),
            ("rule:phone", "doxxing"), ("lex:promo", "spam_promo"),
            ("rule:email", "spam_promo"), ("rule:url", "spam_promo"),
            ("lex:insult", "insult"))

AUDIT_EXPAND_AT = 0.2
AUDIT_MAX_SHARE = 0.5


class NoJudgeEndpoint(RuntimeError):
    """Raised when the judge can't be reached; the caller falls back to --no-judge."""


def parse_input(input_path: str | Path) -> tuple:
    from persocial.ingest.parsers import parse_file

    p = Path(input_path)
    data = p.read_bytes()
    parsed = parse_file(p.name, data)
    if parsed.source == "post_metrics_csv" or not parsed.comments:
        raise ValueError(f"{p.name}: no comments to triage (source {parsed.source})")
    return parsed, hashlib.sha256(data).hexdigest()


def ensure_scored(store: store_mod.Store, device: str | None = None) -> dict:
    from persocial.scoring.core import MODEL_VERSION, Scorer

    pending = store.unscored()
    if not pending:
        return {"scored": 0, "device": device or settings().scoring_device}
    cached, _ = models_cached()
    if not cached:
        print("first run: downloading ~1.1 GB of scoring models "
              "(tip: `persocial models pull` pre-downloads them)")
    scorer = Scorer(device or settings().scoring_device)
    print(f"scoring {len(pending)} comments on {scorer.runner}")
    done = 0
    for i in range(0, len(pending), scorer.batch_size):
        chunk = pending[i:i + scorer.batch_size]
        results = scorer.score([c["text"] or "" for c in chunk])
        for c, (sent, emo) in zip(chunk, results):
            store.update_score(c["ig_id"], sent, emo, MODEL_VERSION)
        done += len(chunk)
        print(f"  {done}/{len(pending)}", flush=True)
    return {"scored": done, "device": scorer.runner}


def _close_skipped(store: store_mod.Store, rows: list[dict], reason: str) -> int:
    """Rows select() skipped (emoji-only, empty) still need a verdict so re-runs
    are stable and reports are complete. State-based: anything in scope that is
    still unjudged gets keep."""
    still = {r["ig_id"] for r in store.unjudged()}
    n = 0
    for r in rows:
        if r["ig_id"] in still:
            store.update_judgment(r["ig_id"], selection="", signals=[],
                                  verdict="keep", category="none", severity=0,
                                  confidence=None, reason=reason, welfare=False)
            n += 1
    return n


def nlp_verdict(signals: list[str]) -> tuple[str, str, int, bool, str]:
    """NLP-only verdict for one candidate: hide for scam/wallet, else review."""
    category = "none"
    for sig, cat in _NLP_CAT:
        if sig in signals:
            category = cat
            break
    verdict = "hide" if set(signals) & _NLP_HIDE else ("review" if signals else "keep")
    severity = 3 if verdict == "hide" else (2 if verdict == "review" else 0)
    final, welfare = apply_policy(verdict, category, severity)
    return final, category, severity, welfare, f"nlp:{','.join(signals) or 'none'}"


def triage_nlp(store: store_mod.Store, lexicon) -> dict:
    rows = store.unjudged()
    sel = select(rows, lexicon)
    for it in sel.candidates:
        v, cat, sev, wel, reason = nlp_verdict(it.signals)
        store.update_judgment(it.ig_id, selection="candidate", signals=it.signals,
                              verdict=v, category=cat, severity=sev,
                              confidence=None, reason=reason, welfare=wel)
    audit = draw_audit(sel.pool, max(settings().audit_min, len(sel.candidates)),
                       random.Random(0), 1)
    for it in audit:
        store.update_judgment(it.ig_id, selection="audit", signals=it.signals,
                              verdict="keep", category="none", severity=0,
                              confidence=None, reason="nlp:audit sample", welfare=False)
    for it in sel.pool:
        store.update_judgment(it.ig_id, selection="", signals=[],
                              verdict="keep", category="none", severity=0,
                              confidence=None, reason="nlp:clean", welfare=False)
    skipped = _close_skipped(store, rows, "skip:emoji-only")
    return {"candidates": len(sel.candidates), "audit": len(audit),
            "skipped": skipped}


def _judge_model_row(model_name: str) -> dict:
    return {"id": "tier1", "label": "tier1 judge", "base_url": "",
            "model": model_name, "api_key_env": None, "batch_size": 10,
            "disable_thinking": True, "enabled": True}


def judge_items(store: store_mod.Store, items: list, model_row: dict,
                system_prompt: str) -> int:
    """Judge items with fan-out over duplicate texts. Returns flagged count."""
    groups = group(items)
    flagged = 0
    by_post: dict[str, list] = {}
    for g in groups.values():
        by_post.setdefault(g[0].post_code or "", []).append(g)
    verdicts: dict[str, dict] = {}
    for gs in by_post.values():
        for i in range(0, len(gs), int(model_row["batch_size"])):
            chunk = gs[i:i + int(model_row["batch_size"])]
            res = client.judge_batch(model_row, system_prompt,
                                     [(g[0].ig_id, g[0].text) for g in chunk],
                                     "", "")
            verdicts.update(res.verdicts)
    for g in groups.values():
        v = verdicts.get(g[0].ig_id, {"verdict": "review", "category": "none",
                                      "severity": 2, "confidence": None,
                                      "reason": "judge_error"})
        verdict, welfare = apply_policy(v["verdict"], v["category"], v["severity"])
        for it in g:
            store.update_judgment(
                it.ig_id, selection=it.selection, signals=it.signals,
                verdict=verdict, category=v["category"], severity=v["severity"],
                confidence=v.get("confidence"), reason=v.get("reason") or "",
                welfare=welfare)
        if verdict in ("hide", "review"):
            flagged += len(g)
    return flagged


def triage_judge(store: store_mod.Store, lexicon, pack_names: tuple[str, ...],
                 seed: int = 0) -> dict:
    base = doctor.judge_base()
    model_name = settings().judge_model
    if not doctor.judge_reachable(base):
        raise NoJudgeEndpoint(
            f"no judge endpoint at {base} — start it or re-run with --no-judge")
    if not model_name:
        raise NoJudgeEndpoint(
            "PERSOCIAL_JUDGE_MODEL is empty — set it to the loaded model id "
            "or re-run with --no-judge")
    model_row = _judge_model_row(model_name)
    try:
        client.ensure_loaded(model_row)
    except client.ModelNotLoaded as e:
        raise NoJudgeEndpoint(str(e)) from None
    prompt = lex_mod.prompt_for(pack_names)
    rows = store.unjudged()
    sel = select(rows, lexicon)
    for it in sel.candidates:
        it.selection = "candidate"
    judge_items(store, sel.candidates, model_row, prompt)
    rounds = []
    budget = int((len(sel.candidates) + len(sel.pool)) * AUDIT_MAX_SHARE)
    k = max(settings().audit_min, len(sel.candidates))
    rng = random.Random(seed)
    audited = 0
    while sel.pool and audited < budget:
        draw = draw_audit(sel.pool, min(k, int(budget - audited)), rng, len(rounds) + 1)
        if not draw:
            break
        rate = judge_items(store, draw, model_row, prompt) / len(draw)
        audited += len(draw)
        rounds.append({"round": len(rounds) + 1, "drawn": len(draw),
                       "rate": round(rate, 3), "expand": rate >= AUDIT_EXPAND_AT})
        if rate < AUDIT_EXPAND_AT:
            break
    for it in sel.pool:
        store.update_judgment(it.ig_id, selection="", signals=[],
                              verdict="keep", category="none", severity=0,
                              confidence=None, reason="pool:not selected", welfare=False)
    skipped = _close_skipped(store, rows, "skip:emoji-only")
    judged = store.conn.execute(
        "select verdict, count(*) n from comments where verdict <> '' group by verdict"
    ).fetchall()
    return {"candidates": len(sel.candidates), "skipped": skipped, "audit_rounds": rounds,
            "audit": audited,
            "verdicts": {r["verdict"]: r["n"] for r in judged},
            "model": model_name}


def run(input: str, out: str = "triage", formats=("xlsx", "csv", "html"),
        packs=None, no_judge: bool = False, device: str | None = None) -> dict:
    pack_names = lex_mod.resolve_packs(packs)
    lex = lex_mod.build_lexicon(pack_names)
    parsed, digest = parse_input(input)
    filename = Path(input).name
    print(f"parsed {parsed.source}: {len(parsed.comments)} comments, "
          f"{len(parsed.rejects)} rejects")
    store = store_mod.Store()
    try:
        res = store.upsert_parsed(parsed, filename, digest)
        print(f"store {store.path}: +{res['inserted']} new, {res['existing']} existing")
        score_info = ensure_scored(store, device)
        judge_mode = "nlp-only"
        if no_judge:
            tri = triage_nlp(store, lex)
        else:
            try:
                tri = triage_judge(store, lex, pack_names, seed=int(digest[:8], 16))
                judge_mode = f"llm:{tri['model']}"
            except NoJudgeEndpoint as e:
                print(f"warning: {e} (NLP-only triage)")
                tri = triage_nlp(store, lex)
        stats = store.stats()
        extra = {"judge": judge_mode, "packs": ",".join(pack_names),
                 "device": score_info.get("device", "")}
        rows = store.all_comments()
        written = []
        out_p = Path(out)
        if "xlsx" in formats:
            report_mod.write_xlsx(out_p.with_suffix(".xlsx"), rows, extra)
            written.append(str(out_p.with_suffix(".xlsx")))
        if "csv" in formats:
            report_mod.write_csv(out_p.with_suffix(".csv"), rows)
            written.append(str(out_p.with_suffix(".csv")))
        if "html" in formats:
            report_mod.write_html(out_p.with_suffix(".html"), rows, extra)
            written.append(str(out_p.with_suffix(".html")))
        print("wrote " + " ".join(written))
        return {"parsed": len(parsed.comments), **res, **stats, **tri,
                "judge_mode": judge_mode, "outputs": written}
    finally:
        store.close()
