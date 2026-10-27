"""Gulf/MSA/Egyptian dialect pack: dialect cues, Arabizi spellings and spam/scam
patterns for Arabic comment sections. No political or regime terms (G1)."""

from __future__ import annotations

LEXICON: tuple[tuple[str, str], ...] = (
    # dialect abuse (mild, non-political)
    ("يا غبي", "insult"), ("تافه", "insult"), ("قذر", "insult"),
    ("كل تبن", "insult"), ("وسخ", "insult"), ("حقير", "insult"),
    ("7mar", "insult"), ("hamar", "insult"),  # donkey, Arabizi
    # money / earn scams in dialect
    ("حوالة", "scam"), ("ارباح", "scam"), ("استثمار", "scam"), ("اربح", "scam"),
    # promo in dialect
    ("فولو باك", "promo"), ("زوروا", "promo"), ("رابط البايو", "promo"),
    # allow-list politeness (dialect forms)
    ("الله يعطيك العافية", "allow"), ("يعطيك العافية", "allow"),
    ("تستاهل كل خير", "allow"), ("حبيبي", "allow"),
)

PROMPT_APPENDIX = """Dialect notes: Gulf, Egyptian and Levantine slang and Arabizi are common.
Affectionate and polite forms ("حبيبي", "7abibi", "تستاهل كل خير", "الله يعطيك العافية")
are keep. Dialect insults ("يا غبي", "تافه", "كل تبن", "7mar") still count as insults.
Money-transfer, investment and "اربح" pitches are spam_scam; follow-back and
"زوروا الرابط" pitches are spam_promo."""

NORM_HINTS: tuple[tuple[str, str], ...] = (
    ("چ", "ج"),  # Persian peze-vi form of ج
    ("گ", "ك"),  # Persian form of ك
)
