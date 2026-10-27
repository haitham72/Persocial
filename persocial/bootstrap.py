"""Seed defaults into an empty database (models, prompt v1, starter lexicon). Idempotent —
never touches rows that already exist, so edits made in the Judge Lab survive restarts."""

from __future__ import annotations

from persocial import db
from persocial.judge.packs import pack_lexicon, pack_prompt_appendix
from persocial.judge.taxonomy import DEFAULT_MODELS, PROMPT_V1, SEED_LEXICON


def ensure_defaults() -> None:
    with db.tx() as conn:
        if not conn.execute("select 1 from models limit 1").fetchone():
            for mid, label, base, model, bs, default in DEFAULT_MODELS:
                conn.execute(
                    """insert into models (id, label, base_url, model, batch_size, is_default)
                       values (%s,%s,%s,%s,%s,%s)""", (mid, label, base or "", model, bs, default))
        if not conn.execute("select 1 from prompts limit 1").fetchone():
            prompt = PROMPT_V1
            appendix = pack_prompt_appendix()
            if appendix:
                prompt += "\n\n" + appendix
            conn.execute("""insert into prompts (version, notes, system_prompt, is_active)
                            values ('v1', 'seed: neutral taxonomy', %s, true)""", (prompt,))
        for term, kind in [*SEED_LEXICON, *pack_lexicon()]:
            conn.execute("""insert into lexicon (term, kind, note) values (%s,%s,'seed')
                            on conflict (term, kind) do nothing""", (term, kind))


def load_demo() -> str:
    """Ingest the synthetic sample export (examples/sample/) so a fresh stack, and the guest
    login, have something to show. Files are deduplicated by hash, so re-running adds nothing."""
    from persocial.config import REPO_ROOT
    from persocial.ingest.service import ingest_file

    f = REPO_ROOT / "examples" / "sample" / "generic.csv"
    r = ingest_file(f.name, f.read_bytes(), account_hint="demo_bakery")
    return (f"demo data already loaded ({f.name})" if r.duplicate_file
            else f"demo data loaded: +{r.rows_inserted} comments from {f.name}")
