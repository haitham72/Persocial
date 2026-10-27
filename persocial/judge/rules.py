"""Deterministic signals: cheap, explainable reasons to send a comment to the judge even
when the sentiment model calls it neutral/positive (scam markers, coded insults), or to
skip it (emoji-only love, allow-listed idioms the sentiment model misreads)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from persocial.judge.packs import norm_hints
from persocial.text import arabizi_variant, normalize

_PATTERNS = {
    "url": re.compile(r"(https?://|www\.|\b[\w-]+\.(com|net|org|io|me|link|ly|xyz|shop)\b)", re.IGNORECASE),
    "phone": re.compile(r"(\+?\d[\d\s\-()]{8,}\d)"),
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"),
    "wallet": re.compile(r"\b(0x[a-fA-F0-9]{30,}|[13][a-km-zA-HJ-NP-Z1-9]{25,34}|T[A-Za-z1-9]{33})\b"),
}

# emotion labels that pull a comment in on their own vs only raise priority. From the corpus
# read: annoyance/disgust are rare but real; anger is mostly "Killer 🔥" noise unless the
# comment is also negative; disapproval is mostly negations ("No") — excluded.
EMOTION_TRIGGERS = {"annoyance", "disgust"}
EMOTION_BOOST = {"anger"}


@dataclass
class LexTerm:
    term: str
    kind: str
    is_regex: bool
    pattern: re.Pattern | None = None


def load_lexicon() -> list[LexTerm]:
    from persocial import db  # cloud/DB path only; keeps Tier 1 importable without psycopg
    out = []
    for r in db.fetch_all("select term, kind, is_regex from lexicon where enabled"):
        t = LexTerm(r["term"], r["kind"], r["is_regex"])
        if t.is_regex:
            try:
                t.pattern = re.compile(r["term"], re.IGNORECASE)
            except re.error:
                continue
        else:
            t.term = normalize(t.term)
        out.append(t)
    return out


def signals_for(text: str, text_norm: str, sentiment: str | None, emotion: str | None,
                lexicon: list[LexTerm]) -> tuple[list[str], bool]:
    """Returns (signals, allow_hit). Signals prefixed: neg, emo:, rule:, lex:."""
    sig: list[str] = []
    if sentiment == "negative":
        sig.append("neg")
    if emotion in EMOTION_TRIGGERS or emotion in EMOTION_BOOST and sentiment == "negative":
        sig.append(f"emo:{emotion}")
    for name, pat in _PATTERNS.items():
        if pat.search(text):
            sig.append(f"rule:{name}")
    allow = False
    probe = text_norm
    for old, new in norm_hints():
        probe = probe.replace(old, new)
    variant = arabizi_variant(probe)
    for t in lexicon:
        hit = t.pattern.search(text) if t.pattern else (t.term in probe or t.term in variant)
        if not hit:
            continue
        if t.kind == "allow":
            allow = True
        else:
            sig.append(f"lex:{t.kind}")
    return sorted(set(sig)), allow
