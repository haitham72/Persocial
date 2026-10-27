# Taxonomy & region packs

How the judge classifies comments, and how to extend it for a new dialect/region without
touching code.

## Categories

| Category | Default | Severity | Meaning |
|---|---|---|---|
| `insult` | hide | 3 | Profanity, slurs, name-calling aimed at a person, the account owner, a nationality or group |
| `public_figure_attack` | hide | 3 | Abuse of or contempt for the account owner or a public figure they represent (puppet, traitor, takfir) — even phrased as a question or prayer |
| `threat` | hide | 3 | Threats, incitement, curses wishing harm |
| `sectarian` | hide | 3 | Religious or sectarian hate |
| `harassment` | hide | 2–3 | Targeting another commenter or a named private person |
| `defamation` | hide | 2–3 | False claims, rumours or conspiracy about the account owner or named people |
| `sexual` | hide | 3 | Sexual content, slurs or advances |
| `doxxing` | hide | 3 | Phone numbers, addresses or identities posted to expose a private person |
| `spam_scam` | hide | 2–3 | Fraud: crypto/wallet asks, fake giveaways, earn-money, phishing, impersonating the account |
| `spam_promo` | hide | 2 | Advertising a product, service, page or account |
| `spam_bot` | review | 2 | Bot engagement: follow-for-follow, copy-paste praise |
| `spam_flood` | keep | 1 | The same harmless text repeated many times by fans |
| `spam_fun` | keep | 0–1 | Harmless noise: tagging friends, "first", emoji floods |
| `political_criticism` | review | 2 | Criticism of politics or public institutions without abuse |
| `religious_idiom` | review | 2 | Ambiguous religious phrase (حسبي الله, الله يهديك) |
| `welfare` | review | 2 | Commenter may be at risk — always escalate, never hide |
| `appeal` | keep | 0 | Asking the account owner for help (visa, money, medical) |
| `grievance` | keep | 1 | Respectful complaint about a service or decision |
| `grief` | keep | 0 | Condolences, du'a for the deceased, sadness |
| `none` | keep | 0 | Nothing to act on |

Severity: **0** harmless · **1** mild / harmless spam · **2** sensitive, needs a human ·
**3** clearly hide. `apply_policy` in `persocial/judge/taxonomy.py` reconciles the model's
verdict with the category default (severity 3 always hides; welfare always reviews).

Source of truth: `persocial/judge/taxonomy.py` (`CATEGORIES`, `PROMPT_V1`, `SEED_LEXICON`).
The prompt and lexicon are *seeded into the database* at bootstrap — iterate there via the
Judge Lab page, not by editing the file.

## Region packs

A **pack** is an optional dialect/locale add-on selected with:

```
PERSOCIAL_PACKS=generic            # default
PERSOCIAL_PACKS=generic,gulf_ar    # combine packs
```

A pack contributes three things (see `persocial/judge/packs/`):

1. **Lexicon seeds** — extra `(term, kind)` rows appended to `SEED_LEXICON` at bootstrap.
   `kind` must be one of the CHECK values in the schema (`insult`, `public_figure_attack`,
   `threat`, `sectarian`, `sexual`, `scam`, `promo`, `allow`).
2. **Prompt appendix** — plain text appended to `PROMPT_V1` when the prompt is first seeded.
   Tells the model about dialect forms, affectionate idioms, local spam patterns.
3. **Norm hints** — literal `(from, to)` replacements applied to the normalised comment text
   before lexicon matching (e.g. Persian `چ→ج`, `گ→ك`). Cheap, explainable, no regex.

Built-in packs:

- **`generic`** (default) — nothing extra; the base taxonomy is already neutral.
- **`gulf_ar`** — Gulf/Egyptian/Levantine dialect abuse (`يا غبي`, `تافه`, `كل تبن`), Arabizi
  spellings (`7mar`, `hamar`), dialect money-scam markers (`حوالة`, `ارباح`, `استثمار`),
  politeness allow-list (`الله يعطيك العافية`, `تستاهل كل خير`), and `چ/گ` norm hints.
  **No political or regime terms** (review.md G1).

### Writing a new pack

1. Create `persocial/judge/packs/<name>.py` exporting `LEXICON`, `PROMPT_APPENDIX`,
   `NORM_HINTS` (all optional).
2. Register it in `PACKS` in `persocial/judge/packs/__init__.py`.
3. Add tests in `tests/test_packs.py` — kinds must be valid, no political terms.
4. Re-run bootstrap (`persocial` CLI or drop/recreate the DB) — the prompt row and lexicon
   are only seeded when empty; changing `PERSOCIAL_PACKS` after first bootstrap does **not**
   update existing DB rows (edit them in Judge Lab or wipe the DB).
