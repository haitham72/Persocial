"""Local lexicon + prompt: SEED_LEXICON plus the active region packs, normalised the
same way the Tier 2 bootstrap seeds the DB (persocial/bootstrap.py) and the eval
harness builds its probe lexicon (evals/run_eval.py). No DB needed."""

from __future__ import annotations

from persocial.judge.packs import PACKS
from persocial.judge.rules import LexTerm
from persocial.judge.taxonomy import PROMPT_V1, SEED_LEXICON
from persocial.text import normalize


def resolve_packs(names: str | list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if names is None:
        from persocial.config import settings

        names = settings().persocial_packs
    if isinstance(names, str):
        names = tuple(n.strip() for n in names.split(",") if n.strip())
    unknown = [n for n in names if n not in PACKS]
    if unknown:
        raise ValueError(f"unknown packs: {unknown}; known: {sorted(PACKS)}")
    return tuple(names) or ("generic",)


def build_lexicon(pack_names: str | list[str] | tuple[str, ...] | None = None) -> list[LexTerm]:
    names = resolve_packs(pack_names)
    terms = list(SEED_LEXICON)
    for name in names:
        terms.extend(PACKS[name].LEXICON)
    return [LexTerm(normalize(t), kind, False) for t, kind in terms]


def prompt_for(pack_names: str | list[str] | tuple[str, ...] | None = None) -> str:
    names = resolve_packs(pack_names)
    parts = [getattr(PACKS[n], "PROMPT_APPENDIX", "").strip() for n in names]
    appendix = "\n".join(p for p in parts if p)
    return PROMPT_V1 + ("\n\n" + appendix if appendix else "")
