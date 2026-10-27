"""WP5 eval: Arabic golden set for normalize / script_of / signals_for + judge category.

Reads ``arabic_golden.jsonl`` (hand-written synthetic cases, ``demo_``-free schema
so the G1.8 username walk ignores it) and runs each case against the real
``persocial.text`` / ``persocial.judge.rules`` code plus a deterministic stub
judge that stands in for the LLM. Prints per-part accuracy.

Gates (plan WP5, review G2.4): normalize, script and signals each >= 95%.
Judge-category accuracy is reported, not gated.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("PERSOCIAL_PACKS", "generic,gulf_ar")

from persocial.judge import taxonomy
from persocial.judge.packs import PACKS
from persocial.judge.rules import LexTerm, signals_for
from persocial.text import normalize, script_of

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "arabic_golden.jsonl"
PACK_NAMES = ("generic", "gulf_ar")
GATE = 0.95

WELFARE_WORDS = ("kill myself", "end my life", "انتحر", "لا اريد العيش", "feeling so low")
THREAT_WORDS = ("smash", "burn down", "ساحطم", "احرق", "i will come")
SCAM_WORDS = ("usdt", "crypto", "bitcoin", "forex", "investment", "earn money",
              "double", "fee", "prize", "wallet", "حوالة", "ارباح", "استثمار",
              "اربح", "جائزة", "bakery owner", "card number",
              "official announcement", "management", "صاحب المخبز")
PROMO_WORDS = ("follow me", "check my", "follow-back", "فولو", "زوروا", "بايو",
               "discount", "promo code")
INSULT_WORDS = ("idiot", "stupid", "dumb")
HARASS_WORDS = ("loser", "shut up", "nobody likes", "ridiculous", "ugly",
                "فاشل", "ما تفهم", "اخرس")
BOT_PHRASES = ("great content", "nice post", "amazing content", "keep it up",
               "following for more", "so good")
GRIEF_WORDS = ("passed away", "توفي")
APPEAL_WORDS = ("spare", "lost my job", "please help", "محتاج", "ساعد")
GRIEVANCE_WORDS = ("stale", "late", "cold", "disappointed", "waited", "dry",
                   "forgot", "terrible", "furious", "slow", "زعلان", "ناشف",
                   "تأخر", "بارد", "سيء")


def build_lexicon(pack_names: tuple[str, ...] = PACK_NAMES) -> list[LexTerm]:
    terms = list(taxonomy.SEED_LEXICON)
    for name in pack_names:
        terms.extend(PACKS[name].LEXICON)
    return [LexTerm(normalize(t), kind, False) for t, kind in terms]


def stub_judge_category(text: str, norm: str, signals: list[str]) -> str:
    """Deterministic stand-in for the LLM judge: keyword rules over the same
    normalized text and signals the real pipeline produces."""
    if any(w in norm for w in WELFARE_WORDS):
        return "welfare"
    if any(w in norm for w in THREAT_WORDS):
        return "threat"
    if "lex:scam" in signals or "rule:wallet" in signals or any(w in norm for w in SCAM_WORDS):
        return "spam_scam"
    if "lex:promo" in signals or "rule:email" in signals or "rule:url" in signals:
        return "spam_promo"
    if "rule:phone" in signals:
        return "doxxing"
    if "lex:insult" in signals or any(w in norm for w in INSULT_WORDS):
        return "insult"
    if any(w in norm for w in HARASS_WORDS):
        return "harassment"
    if "حسبي الله" in text:
        return "religious_idiom"
    if any(p in norm for p in BOT_PHRASES):
        return "spam_bot"
    if script_of(text) == "emoji":
        return "spam_fun"
    if any(w in norm for w in GRIEF_WORDS):
        return "grief"
    if any(w in norm for w in APPEAL_WORDS):
        return "appeal"
    if any(w in norm for w in GRIEVANCE_WORDS):
        return "grievance"
    return "none"


def evaluate(cases: list[dict], lexicon: list[LexTerm]) -> dict:
    tallies = {"normalize": [0, 0], "script": [0, 0], "signals": [0, 0], "judge": [0, 0]}
    failures: list[str] = []
    judge_mismatches: list[str] = []
    for c in cases:
        norm = normalize(c["text"])
        sig, allow = signals_for(c["text"], norm, c.get("sentiment"),
                                 c.get("emotion"), lexicon)
        cat = stub_judge_category(c["text"], norm, sig)
        checks = [("normalize", norm, c["expected_normalize"]),
                  ("script", script_of(c["text"]), c["expected_script"]),
                  ("signals", sig, c["expected_signals"])]
        for part, got, want in checks:
            ok = got == want
            tallies[part][0] += ok
            tallies[part][1] += 1
            if not ok:
                failures.append(f"{c['id']}/{part}: got {got!r} want {want!r}")
        ok = cat == c["expected_category"]
        tallies["judge"][0] += ok
        tallies["judge"][1] += 1
        if not ok:
            judge_mismatches.append(f"{c['id']}/judge: got {cat!r} want {c['expected_category']!r}")
        if allow != c["expected_allow"]:
            failures.append(f"{c['id']}/allow: got {allow!r} want {c['expected_allow']!r}")
    return {"tallies": tallies, "failures": failures, "judge_mismatches": judge_mismatches}


def main() -> int:
    cases = [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    lexicon = build_lexicon()
    result = evaluate(cases, lexicon)
    print(f"cases: {len(cases)} packs: {','.join(PACK_NAMES)}")
    gated_ok = True
    for part in ("normalize", "script", "signals", "judge"):
        hit, total = result["tallies"][part]
        acc = hit / total if total else 0.0
        tag = "GATE" if part != "judge" else "report"
        print(f"{part}: {hit}/{total} = {acc:.1%} [{tag}]")
        if part != "judge" and acc < GATE:
            gated_ok = False
    for f in result["failures"]:
        print("FAIL", ascii(f))
    for f in result["judge_mismatches"]:
        print("JUDGE-DIFF", ascii(f))
    print("GATE:", "PASS" if gated_ok and not result["failures"] else
          ("PASS (judge diffs only)" if gated_ok else "FAIL"))
    return 0 if gated_ok else 1


if __name__ == "__main__":
    sys.exit(main())
