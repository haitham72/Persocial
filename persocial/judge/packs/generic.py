"""Generic pack — the default. The base taxonomy and SEED_LEXICON in taxonomy.py are
already generic; this pack contributes nothing extra. Exists so a deployment can run
`PERSOCIAL_PACKS=generic` explicitly, and as a template for custom packs."""

LEXICON: tuple[tuple[str, str], ...] = ()

PROMPT_APPENDIX = ""

NORM_HINTS: tuple[tuple[str, str], ...] = ()
