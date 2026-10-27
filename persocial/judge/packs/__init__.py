"""Region packs: optional dialect/locale add-ons selected with PERSOCIAL_PACKS
(comma-separated, default "generic"). A pack contributes three things:

  lexicon seeds       extra (term, kind) rows seeded into the lexicon at bootstrap
  prompt appendix     text appended to PROMPT_V1 when the prompt is first seeded
  normalization hints literal (from, to) replacements applied to the normalised text
                      before lexicon matching (rules.signals_for)

Packs must stay political/regime-free (review.md G1)."""

from __future__ import annotations

from persocial.config import settings
from persocial.judge.packs import generic, gulf_ar

PACKS = {
    "generic": generic,
    "gulf_ar": gulf_ar,
}


def active_packs() -> tuple[str, ...]:
    names = [p.strip() for p in settings().persocial_packs.split(",") if p.strip()]
    unknown = [n for n in names if n not in PACKS]
    if unknown:
        raise ValueError(f"unknown packs: {unknown}; known: {sorted(PACKS)}")
    return tuple(names or ["generic"])


def pack_lexicon() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for name in active_packs():
        out.extend(getattr(PACKS[name], "LEXICON", ()))
    return out


def pack_prompt_appendix() -> str:
    parts = [getattr(PACKS[n], "PROMPT_APPENDIX", "").strip() for n in active_packs()]
    return "\n".join(p for p in parts if p)


def norm_hints() -> tuple[tuple[str, str], ...]:
    out: list[tuple[str, str]] = []
    for name in active_packs():
        out.extend(getattr(PACKS[name], "NORM_HINTS", ()))
    return tuple(out)
