"""Text normalisation shared by ingest (dedup key, script class), the lexicon matcher and the
judge's duplicate fan-out. Arabic-aware: diacritics, tatweel, letter-form variants and
stretched letters all collapse, so "اللــــه" / "الله" / "ٱللَّه" are one key and a blocklist
term can't be dodged by decoration.
"""

from __future__ import annotations

import re
import unicodedata

_AR_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭ]")
_TATWEEL = "ـ"
_AR_FOLD = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    "ى": "ي", "ئ": "ي",
    "ؤ": "و",
    "ة": "ه",
    "ک": "ك", "ی": "ي",           # Persian/Urdu forms seen in the corpus
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
})
_ZERO_WIDTH = re.compile("[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
_REPEAT = re.compile(r"(.)\1{2,}")           # "سلاااام" -> "سلاام", "loooove" -> "loove"
_WS = re.compile(r"\s+")
_MENTION = re.compile(r"(?<!\S)@[\w.]+")
_URL = re.compile(r"(https?://\S+|www\.\S+)", re.IGNORECASE)

_ARABIC_CHAR = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
_LATIN_CHAR = re.compile(r"[A-Za-zÀ-ɏ]")
_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)

# Arabizi digits -> the Arabic letter they stand for, only applied for lexicon matching.
_ARABIZI = str.maketrans({"2": "ء", "3": "ع", "5": "خ", "6": "ط", "7": "ح", "8": "ق", "9": "ص"})


def normalize(text: str) -> str:
    """Dedup/match key. Lowercase, NFKC, Arabic folded, mentions/urls masked, stretched
    letters squeezed to two, whitespace collapsed. Emojis are kept — "❤️❤️" and "❤️" stay
    distinct texts but each is judged once however often it repeats."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = _ZERO_WIDTH.sub("", t)
    t = _AR_DIACRITICS.sub("", t).replace(_TATWEEL, "")
    t = t.translate(_AR_FOLD).lower()
    t = _URL.sub("<url>", t)
    t = _MENTION.sub("@user", t)
    t = _REPEAT.sub(r"\1\1", t)
    return _WS.sub(" ", t).strip()


def arabizi_variant(norm: str) -> str:
    """Second matching surface for Latin-script Arabic ("7mar" -> "حmar"); only meaningful
    for lexicon terms written that way, so it's matched in addition to, not instead of."""
    return norm.translate(_ARABIZI)


def script_of(text: str) -> str:
    """arabic | latin | mixed | emoji | other — by letter counts, not language ID, because
    code-switched comments are common and a single language label would hide half of them."""
    if not text or not text.strip():
        return "other"
    ar = len(_ARABIC_CHAR.findall(text))
    la = len(_LATIN_CHAR.findall(text))
    if ar == 0 and la == 0:
        return "emoji" if not _LETTER.search(text) and any(ord(ch) > 0x2000 for ch in text) else "other"
    if ar and la:
        share = ar / (ar + la)
        if 0.2 <= share <= 0.8:
            return "mixed"
        return "arabic" if share > 0.8 else "latin"
    return "arabic" if ar else "latin"


def is_emoji_only(text: str) -> bool:
    return script_of(text) == "emoji"


def model_input(text: str) -> str:
    """What the NLP models see — @user / http preprocessing shared with the Colab
    scorer, so scores stay comparable across backends."""
    t = re.sub(r"(?<!\S)@\S+", "@user", text or "")
    return re.sub(r"http\S*", "http", t)
