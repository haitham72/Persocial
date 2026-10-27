"""Which comments the judge sees.

  candidates = any signal (negative sentiment, emotion trigger, rule, lexicon), minus
               allow-listed idioms whose only signal is a weak negative score
  pool       = every other eligible comment — the audit draws from here (see runner:
               X candidates → X random audit comments, expanding while the judge keeps
               finding problems in the audit draws)
  emoji-only comments are never sent (≈0% hostile in the corpus)

Groups collapse duplicates: one representative per normalised text is judged and its
verdict fans out (42% of negatives in the corpus are copy-paste repeats).
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field

from persocial.judge.rules import LexTerm, signals_for


@dataclass
class Item:
    ig_id: str
    text: str
    text_norm: str
    script: str
    sentiment: str | None
    sentiment_score: float | None
    emotion: str | None
    post_code: str = ""
    selection: str = ""                   # candidate | audit
    signals: list[str] = field(default_factory=list)


@dataclass
class Selection:
    candidates: list[Item]
    pool: list[Item]
    skipped: int


def select(rows: list[dict], lexicon: list[LexTerm], *, judge_all: bool = False) -> Selection:
    candidates, pool, skipped = [], [], 0
    for r in rows:
        it = Item(r["ig_id"], r["text"] or "", r["text_norm"] or "", r["script"],
                  r.get("sentiment"), r.get("sentiment_score"), r.get("emotion"),
                  r.get("post_code") or "")
        if not it.text.strip() or it.script == "emoji":
            skipped += 1
            continue
        sig, allow = signals_for(it.text, it.text_norm, it.sentiment, it.emotion, lexicon)
        weak_neg_only = sig == ["neg"] and (it.sentiment_score or 0) < 0.6
        if allow and (not sig or weak_neg_only):
            sig = []
        it.signals = sig
        if sig or judge_all:
            it.selection = "candidate"
            candidates.append(it)
        else:
            pool.append(it)
    return Selection(candidates, pool, skipped)


def draw_audit(pool: list[Item], k: int, rng: random.Random, round_no: int) -> list[Item]:
    """Remove and return k random items from pool, stratified by script so Arabic isn't
    drowned by Latin (each script gets its share, at least one if present)."""
    if k <= 0 or not pool:
        return []
    by_script: dict[str, list[Item]] = defaultdict(list)
    for it in pool:
        by_script[it.script].append(it)
    picked: list[Item] = []
    for _script, items in sorted(by_script.items()):
        share = max(1, round(k * len(items) / len(pool)))
        picked += rng.sample(items, min(share, len(items)))
    picked = picked[:max(k, len(by_script))]
    chosen = {id(it) for it in picked}
    pool[:] = [it for it in pool if id(it) not in chosen]
    for it in picked:
        it.selection = "audit"
        it.signals = [f"audit:r{round_no}"]
    return picked


def group(items: list[Item]) -> dict[str, list[Item]]:
    out: dict[str, list[Item]] = {}
    for it in items:
        out.setdefault(it.text_norm or it.ig_id, []).append(it)
    return out
