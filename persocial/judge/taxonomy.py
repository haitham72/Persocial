"""Judge taxonomy, prompt v1, default models and the seed lexicon.

Grounded in a labelled read of public-figure / brand comment corpora: ~21% of
sentiment-negative comments are hide-worthy, ~17% are borderline political criticism,
and the rest are grief, appeals, respectful grievances or misreads. So the judge must
separate *hostility* from *negativity*, and treat abuse aimed at the account owner or
the public figures they represent as high severity.

Everything here is seed data. Iteration happens in the DB (new prompt versions, lexicon
terms) through the Judge Lab page, not by editing this file.
"""

from __future__ import annotations

# category -> (default action, description shown to the model and in the UI)
CATEGORIES: dict[str, tuple[str, str]] = {
    "insult":              ("hide",   "profanity, slurs, name-calling aimed at a person, the account owner, a nationality or group"),
    "public_figure_attack": ("hide",  "abuse of or contempt for the account owner or a public figure they represent (puppet, traitor, killer, takfir)"),
    "threat":              ("hide",   "threats, incitement, curses wishing harm or destruction"),
    "sectarian":           ("hide",   "religious or sectarian hate (Sunni/Shia, anti-Muslim, anti-Christian, anti-Jewish)"),
    "harassment":          ("hide",   "targeting another commenter or a named private person"),
    "defamation":          ("hide",   "false claims, rumours or conspiracy about the account owner or named people's private lives or crimes"),
    "sexual":              ("hide",   "sexual content, sexual slurs or advances"),
    "doxxing":             ("hide",   "phone numbers, addresses or identities of private people posted to expose them"),
    "spam_scam":           ("hide",   "fraud: crypto/wallet asks, fake giveaways, earn-money, phishing, 'DM me' for money, impersonating the account owner or staff"),
    "spam_promo":          ("hide",   "advertising a product, service, page or account"),
    "spam_bot":            ("review", "bot engagement: follow-for-follow, generic copy-paste praise from fake accounts"),
    "spam_flood":          ("keep",   "the same harmless text repeated many times by fans (copy-paste chants, prayers)"),
    "spam_fun":            ("keep",   "harmless noise: tagging friends, 'first', emoji floods, jokes"),
    "political_criticism": ("review", "criticism of politics, policy or public institutions without abuse — sensitive on a public account"),
    "religious_idiom":     ("review", "religious phrase whose intent is ambiguous (حسبي الله, الله يهديك) — sincere or a jab"),
    "welfare":             ("review", "the commenter may be at risk (suicide, self-harm, abuse) — always escalate"),
    "appeal":              ("keep",   "asking the account owner for help (visa, money, medical, job) — route, don't hide"),
    "grievance":           ("keep",   "respectful complaint about a service or decision"),
    "grief":               ("keep",   "condolences, du'a for the deceased, sadness, missing someone"),
    "none":                ("keep",   "nothing to act on"),
}

SEVERITY = {
    0: "S0 keep — harmless, including negative-but-legitimate",
    1: "S1 keep, note — mild rudeness, harmless spam",
    2: "S2 review — sensitive: political criticism, ambiguous religious idiom, bot spam",
    3: "S3 hide — insult, threat, slur, sectarian hate, sexual, scam/promo, doxxing, public-figure attack",
}


def apply_policy(verdict: str, category: str, severity: int) -> tuple[str, bool]:
    """Model verdict reconciled with the taxonomy. Returns (verdict, welfare_flag).
    Severity 3 always hides; a category whose default is hide is never silently kept;
    welfare always goes to a human."""
    category = category if category in CATEGORIES else "none"
    default = CATEGORIES[category][0]
    if category == "welfare":
        return "review", True
    if severity >= 3 or default == "hide" and verdict == "keep" and severity >= 2:
        return "hide", False
    if verdict not in ("hide", "keep", "review"):
        return default, False
    if severity == 2 and verdict == "keep":
        return "review", False
    return verdict, False


def _category_lines() -> str:
    return "\n".join(f"  {k}: {v[1]}" for k, v in CATEGORIES.items())


PROMPT_V1 = f"""You moderate Instagram comments on a public figure's, brand's or creator's
account. Comments are in Gulf Arabic, MSA, Egyptian Arabic, English, Arabizi (Arabic in
Latin letters with digits: 3=ع 7=ح 5=خ 2=ء) and many other languages.

Input JSON: {{"account": "@handle", "post_caption": "...", "comments": {{"1": "text", ...}}}}.
The ids are throwaway — echo back exactly the ids you were given, no others.

Judge HOSTILITY, not negativity. Most negative-sounding comments are legitimate and must
stay: grief and du'a for the deceased, sadness, people asking the account owner for help
(visa, money, medical), respectful complaints, humanitarian pleas. These are keep.

Categories:
{_category_lines()}

Severity: 0 harmless · 1 mild/harmless spam · 2 sensitive, needs a human · 3 clearly hide.

Rules:
- Abuse or contempt aimed at the account owner or a public figure they represent is
  severity 3 (public_figure_attack) even when phrased as a question or a prayer.
- Short coded insults count even without negative words: animal names for people,
  slurs used as labels, coded religious or political insults.
- Praise written as poetry often uses war imagery (stab, enemies, swords): that is
  praise — keep.
- "MashAllah", "Allah yarhamo", emoji-only love, and du'a are keep even if they look sad.
- حسبي الله ونعم الوكيل / الله يهديك: keep when aimed at a situation; religious_idiom
  (severity 2) when aimed at a person.
- False claims circulated as fact about the account owner (fake announcements, fake
  giveaways, impersonating the account or its staff): treat as the closest category
  (spam_scam for money asks, defamation for reputation lies), severity 2-3.
- A complaint pasted many times as a template is spam_flood, not a grievance.
- Quoting abuse to condemn it ("don't call people ugly") is keep.
- Phone numbers, wallets or names posted to expose a private person: doxxing, severity 3.
- Anyone saying they are in danger or want to end their life: welfare.
- When unsure between keep and hide, choose review with severity 2. Never guess hide.

Reply with ONE strict JSON object, nothing else. One entry per input id, values only:
{{"1": ["hide"|"keep"|"review", "<category>", <severity 0-3>, <confidence 0.0-1.0>, "<reason, max 6 words>"], ...}}"""


TAXONOMY_V1 = {
    "categories": {k: {"default": v[0], "description": v[1]} for k, v in CATEGORIES.items()},
    "severity": SEVERITY,
}

DEFAULT_MODELS = [
    # id, label, base_url (None = judge_base_url), model, batch_size, default
    ("qwen3.5-9b", "Qwen 3.5 9B (LM Studio)", None, "qwen/qwen3.5-9b", 100, True),
    ("qwen3.5-4b", "Qwen 3.5 4B (LM Studio)", None, "qwen3.5-4b", 10, False),
    ("qwen3.8-27b", "Qwen 3.8 27B (LM Studio)", None, "qwen/qwen3.8-27b", 20, False),
]

# Starter lexicon from the labelled sample's misses (coded insults scored neutral) and the
# common scam markers. Normalised before matching, so letter-form variants are covered.
# Region packs (persocial/judge/packs) add dialect terms on top of this.
SEED_LEXICON = [
    ("صهاين", "insult"), ("خنزير", "insult"), ("ديوث", "insult"), ("قرده", "insult"),
    ("madarchod", "insult"), ("bastard", "insult"), ("fuck", "insult"),
    ("usdt", "scam"), ("bitcoin", "scam"), ("crypto", "scam"), ("forex", "scam"),
    ("investment", "scam"), ("earn money", "scam"), ("dm me", "promo"), ("check my", "promo"),
    ("follow me", "promo"), ("whatsapp", "promo"), ("واتساب", "promo"), ("واتس", "promo"),
    ("ما شاء الله", "allow"), ("ماشاء الله", "allow"), ("mashallah", "allow"),
    ("الله يرحمه", "allow"), ("الله يرحمها", "allow"), ("رحمه الله", "allow"),
]
