"""WP5 synthetic sample generator.

Writes ``examples/sample/{apify.json, apify.csv, generic.csv}`` for the fictional
account ``demo_bakery`` (3 posts, ~300 top-level comments plus owner/user replies).

Deterministic: a fixed seed drives every choice, rows are emitted in id order and
files are written with CRLF newlines, so re-running produces byte-identical files.
All three formats carry the same comments, so the WP4 parity test compares them
against each other. Every username starts with ``demo_`` and every id with ``9000``.

Content is 100% invented: praise, questions, complaints, spam/promo and scam
lures on fake ``.example`` domains, mild harassment (no slurs), one clearly
fictional threat, a few impersonation attempts, one low-mood note, and replies.
Languages: Gulf, MSA and Egyptian Arabic, Arabizi, English, code-switched and
emoji-only. No real people, places, numbers or brands appear anywhere.
"""

from __future__ import annotations

import csv
import io
import json
import random
from datetime import UTC
from pathlib import Path

SEED = 20261026
ACCOUNT = "demo_bakery"
ACCOUNT_ID = "500"

POSTS: tuple[tuple[str, str], ...] = (
    ("DBK001", "Fresh sourdough out of the oven this morning"),
    ("DBK002", "Kunafa Friday pre-orders are open"),
    ("DBK003", "Tasting day: date squares and pistachio croissants"),
)

BASE_TS = 1772323200  # 2026-03-01T08:00:00Z, fixed so output never shifts

USERS: tuple[str, ...] = (
    "demo_layla", "demo_noor", "demo_karim", "demo_huda", "demo_adam",
    "demo_sara", "demo_mariam", "demo_yusuf", "demo_tariq", "demo_dana",
    "demo_rania", "demo_sami", "demo_lina", "demo_faris", "demo_noura",
    "demo_hassan", "demo_rima", "demo_bilal", "demo_salma", "demo_jad",
    "demo_mira", "demo_zeina", "demo_rami", "demo_tala", "demo_nabil",
    "demo_wafaa", "demo_issam", "demo_ghada", "demo_hani", "demo_lubna",
    "demo_mazen", "demo_najwa", "demo_qasim", "demo_rasha", "demo_tamer",
    "demo_wissam",
)

# (group, count) — sums to 300.
QUOTAS: tuple[tuple[str, int], ...] = (
    ("praise_en", 32), ("praise_msa", 24), ("praise_gulf", 24),
    ("praise_egy", 12), ("praise_arabizi", 8), ("praise_emoji", 8),
    ("question_en", 18), ("question_ar", 24), ("question_mixed", 6),
    ("complaint_en", 14), ("complaint_ar", 20),
    ("promo_en", 10), ("promo_ar", 10), ("promo_dialect", 6), ("promo_arabizi", 4),
    ("scam_en", 10), ("scam_ar", 10), ("scam_arabizi", 5),
    ("bot", 12),
    ("harass_ar", 10), ("harass_en", 6), ("harass_arabizi", 4),
    ("codeswitch", 18),
    ("impersonate", 3), ("threat", 1), ("welfare", 1),
)
assert sum(n for _, n in QUOTAS) == 300

TEXTS: dict[str, tuple[str, ...]] = {
    "praise_en": (
        "Love this new sourdough recipe! Soft inside and crusty outside.",
        "The croissants today were perfect, flaky and buttery.",
        "Best bakery around, honestly. The date cake is unreal.",
        "Ordered the family box for the weekend, everyone loved it.",
        "Your kunafa is the best I have tried, sweet but not too sweet.",
        "Fresh bread every morning, you can taste the quality.",
        "The cheese samboosa was still warm when I got home. Amazing.",
        "Thank you for the extra honey cake slice, made my day.",
        "Mashallah the new counter display looks beautiful, congrats.",
        "Tried the pistachio croissant, already planning my next visit.",
        "Soft, fresh, and the staff are always smiling.",
        "The birthday cake you made for my daughter was perfect.",
        "Five stars. The zaatar manakeesh is my weekly fix.",
        "Warm bread, kind people, fair prices. What else do you need.",
        "That date-square tasting sample converted me on the spot.",
        "Crust crackles exactly right. You folks never miss.",
    ),
    "praise_msa": (
        "أحب مخبوزاتكم كثيرا، خبز اليوم كان رائعا.",
        "ما شاء الله، الكرواسون طازج ولذيذ جدا.",
        "شكرا لكم على التعامل الراقي والخبز الطازج.",
        "تجربة جميلة، الحلويات طازجة والأسعار مناسبة.",
        "الكنافة عندكم ممتازة، ليست حلوة زيادة.",
        "طلبت صندوق العائلة للعطلة وكان رائعا.",
        "الخبز يصل ساخنا كل صباح، جودة تستحق الثناء.",
        "كعكة التمر كانت هشة ولذيذة، سأطلب مجددا.",
        "المكان نظيف والموظفون لطفاء جدا.",
        "أوصي الجميع بتجربة فطائر الجبن عندكم.",
        "الفطور عندكم صار عادة أسبوعية لعائلتي.",
        "الله يعطيكم العافية على هذا الجهد الطيب.",
    ),
    "praise_gulf": (
        "الخبز عندكم على كيف كيفك، يعطيكم العافية.",
        "تستاهلون كل خير، مخبز مرتب ونظيف.",
        "الكنافة شي مرتب، عجيبة والله.",
        "حبيبي تسلم يدك على الكرواسون الطازج.",
        "السمبوسة حارة وتوها طالعة من الفرن.",
        "صندوق العائلة يكفي ويوفي، بيضتوا الوجه.",
        "كعك التمر يذوب بالفم، شيء ثاني.",
        "ألذ مناقيش زعتر ذقتها في حياتي.",
        "خبز الصبح عندكم ما يتفوت.",
        "حلاكم مو حالي زيادة، مضبوط تمام.",
        "الفطور عندكم صار عادة يومية.",
        "تعامل راقي وخبز طازج، الله يبارك لكم.",
    ),
    "praise_egy": (
        "الكنافة عندكم جامدة أوي، تسلم إيديكم.",
        "العيش طازة وتحفة، أحلى فطار.",
        "أحلى مخبز جربته في حياتي بجد.",
        "الكرواسون مورق وطعمه حكاية.",
        "ربنا يبارك لكم، حاجة نضيفة ومحترمة.",
        "الفطير عندكم عالمي، هش ومورق.",
        "أسعاركم حلوة والجودة ممتازة.",
        "طلبت للعزومة والكل سألني منين.",
        "الكيكة هشة ومش مسكرة زيادة، عجبتني.",
        "الصبح لازم أبدأ يومي بخبزكم.",
        "تعاملكم ذوق، شكرا يا جماعة.",
        "كحك العيد من عندكم حكاية تانية.",
    ),
    "praise_arabizi": (
        "7abibi this kunafa is 3ajeeb, honestly the best.",
        "mashallah 3alaik, best bakery wallah.",
        "ya gama3a el croissant 7war, lazem tgarabo.",
        "el date cake kan 7elw awi, shokran.",
        "a7la bakery, el 3eish fresh kol yom.",
        "teslam edaik, el kanafa 3alamya.",
        "el family box ykafi w ywaffi, perfect.",
        "kteer tayeb el manakeesh, bravo 3alaik.",
    ),
    "praise_emoji": (
        "❤️❤️❤️", "😍😍😍", "👏👏👏", "❤️🔥❤️",
        "🥐🥐🥐", "😋😋😋", "💯💯💯", "🌙❤️",
    ),
    "question_en": (
        "How much is the family box?",
        "Do you deliver? Need 30 pieces for Friday.",
        "What time do you open in the morning?",
        "Is the kunafa available every day or only Friday?",
        "Do you make sugar-free cakes?",
        "Where is the new counter exactly?",
        "Can I order a birthday cake with one day notice?",
        "Do you have gluten-free bread?",
        "What is in the tasting box on Saturday?",
    ),
    "question_ar": (
        "بكم صندوق العائلة؟",
        "هل يوجد توصيل؟ أحتاج ثلاثين قطعة ليوم الجمعة.",
        "متى تفتحون في الصباح؟",
        "هل الكنافة متوفرة يوميا أم الجمعة فقط؟",
        "هل لديكم كيك بدون سكر؟",
        "أين الفرع الجديد بالضبط؟",
        "هل يمكن طلب كيكة عيد ميلاد قبل يوم واحد؟",
        "هل يوجد خبز خال من الغلوتين؟",
        "ماذا يوجد في صندوق التذوق يوم السبت؟",
        "كم سعر كعكة التمر الكبيرة؟",
        "هل تحضرون طلبات الأعراس الكبيرة؟",
        "هل العجين يباع جاهزا للبيت؟",
    ),
    "question_mixed": (
        "Is التوصيل available on Friday?",
        "بكم ال family box الكبير؟",
        "Do you have كنافة today or only weekends?",
        "ال croissant بالفستق موجود الحين؟",
        "Can I pre-order صناديق للعزومة؟",
        "مواعيد ال tasting day امتى بالضبط؟",
    ),
    "complaint_en": (
        "The bread was stale today, very disappointed.",
        "Waited an hour for my order, too slow.",
        "My cake arrived squashed on one side.",
        "You forgot the extra cheese I paid for.",
        "The soup bread was cold when it reached us.",
        "Ordered at 9, got my box at noon. Not great.",
        "The date cake was too dry this time.",
    ),
    "complaint_ar": (
        "الخبز اليوم كان ناشفا، ما عجبني.",
        "انتظرت ساعة كاملة لاستلام طلبي.",
        "الكيكة وصلت مائلة من جهة.",
        "نسيتم الجبن الإضافي الذي دفعت ثمنه.",
        "الطلب تأخر كثيرا عن الموعد.",
        "كعكة التمر كانت جافة هذه المرة.",
        "الخدمة اليوم كانت بطيئة جدا.",
        "الخبز وصل باردا وهذا أول مرة.",
        "السعر زاد والكمية قلت، ليش؟",
        "طلبت قبل يومين وما وصلني تأكيد.",
    ),
    "promo_en": (
        "Follow me back, I post daily bread recipes! Check my page.",
        "Earn from home baking, DM me for the plan. Check my bio.",
        "Promo code SWEET20 on my cake tools shop, link below.",
        "I sell custom cake toppers, follow me for designs.",
        "Check my page for cheaper boxes, same quality!",
    ),
    "promo_ar": (
        "تابعوني، أنشر وصفات خبز يومية. زوروا صفحتي.",
        "كود خصم للمشتركين الجدد في متجري، الرابط في البايو.",
        "أبيع صواني خبز منزلية، تابعوني للتصاميم.",
        "زوروا صفحتي لصناديق أرخص بنفس الجودة.",
        "من يريد العمل من البيت في الحلويات يراسلني.",
    ),
    "promo_dialect": (
        "فولو باك يا شباب، حسابي كله وصفات.",
        "زوروا الرابط في البايو لعروض الصواني.",
        "تابعوني للخلطات السرية للكرواسون.",
        "عندي حساب أبيع فيه قوالب الكيك، فولو باك.",
        "الرابط في البايو فيه خصم عشرين بالمية.",
        "سوا فولو وردها لك، حساب مخبوزات.",
    ),
    "promo_arabizi": (
        "follow me w check my page for cake tools.",
        "3andi shop lel baking tools, link fel bio.",
        "saw folo w radaha, 7esabi kolo wasafat.",
        "promo code 3ala el qawaleb, check my bio.",
    ),
    "scam_en": (
        "Double your crypto fast! Send 0.01 BTC to win-prize.example/deposit now.",
        "USDT giveaway for bakery fans: claim at https://win-prize.example/usdt before it ends.",
        "Earn money from home with forex, guaranteed profit. Start at https://cash-claim.example/go.",
        "Investment opportunity: put in 100, get 1000 by Friday. Details at https://cash-claim.example/vip.",
        "Bitcoin has doubled again, send to the wallet on https://win-prize.example/btc to join.",
        "Free iPhone for the first 50 followers, register at https://win-prize.example/iphone.",
        "I turned 50 into 5000 with this bot, see https://cash-claim.example/bot.",
        "Crypto airdrop for loyal customers, connect at https://win-prize.example/airdrop.",
        "Make 300 a day liking posts, sign up at https://cash-claim.example/earn.",
        "Your box won a prize! Pay a small fee at https://win-prize.example/fee to release it.",
    ),
    "scam_ar": (
        "ضاعف عملاتك الرقمية بسرعة! أرسل الآن عبر https://win-prize.example/deposit.",
        "توزيع USDT لمتابعي المخبز: استلم عبر https://win-prize.example/usdt قبل انتهاء العرض.",
        "اربح من البيت مع الفوركس، ربح مضمون. ابدأ من https://cash-claim.example/go.",
        "فرصة استثمار: ضع 100 واحصل على 1000. التفاصيل في https://cash-claim.example/vip.",
        "حوالة سريعة بأرباح كبيرة، راسلني على الخاص للتفاصيل.",
        "استثمار مضمون في العملات، الأرباح أسبوعية. من يريد يراسلني.",
        "اربح 300 يوميا من الإعجابات، سجل في https://cash-claim.example/earn.",
        "صندوقك فاز بجائزة! ادفع رسما رمزيا في https://win-prize.example/fee لاستلامها.",
        "البيتكوين ارتفع مجددا، حول الآن عبر https://win-prize.example/btc.",
        "هدية مجانية لأول خمسين متابع، سجل في https://win-prize.example/iphone.",
    ),
    "scam_arabizi": (
        "da3af el crypto bsor3a, eb3at 3ala https://win-prize.example/deposit.",
        "USDT giveaway lel followers, estlem 3ala https://win-prize.example/usdt.",
        "erba7 men el forex, guaranteed profit https://cash-claim.example/go.",
        "7awala saree3a b arba7 kbeera, text me 3al private.",
        "estثمار? la2, real crypto: https://win-prize.example/btc.",
    ),
    "bot": (
        "Great content! Keep it up.",
        "Nice post! Love it.",
        "Amazing content, keep going.",
        "So good! Following for more.",
    ),
    "harass_ar": (
        "يا غبي، حتى الخبز ما تعرف تسويه.",
        "تافه، منشور سخيف مثل صاحبه.",
        "كل تبن واسكت، لا تفتي في الخبز.",
        "وسخ، حسابك كله كذب.",
        "حقير، تسرق وصفات غيرك.",
        "مخك فاضي، لا تكتب مرة ثانية.",
        "اسكت، انت ما تفهم شي.",
        "فاشل، مخبزك بيقفل قريب.",
        "وجهك ما ينفع للدعاية.",
        "اخرس، كلامك كله غلط.",
    ),
    "harass_en": (
        "You are an idiot, even bread is too hard for you.",
        "Shut up loser, nobody asked you.",
        "This is trash and so are you.",
        "Stop posting nonsense every day.",
        "Nobody likes your posts, give up.",
        "You look ridiculous in that apron video.",
    ),
    "harass_arabizi": (
        "inta 7mar wallah, skot a7san.",
        "7mar post honestly, delete it.",
        "skot ya ahbal, ma btفهم شي.",
        "ya tafeh, ma 7ada bi7eb postsak.",
    ),
    "codeswitch": (
        "الكنافة عندكم 10/10 honestly the best.",
        "order وصل بسرعة, thank you so much.",
        "بكم ال family box لو سمحت؟",
        "el croissant كان fresh اليوم, perfect.",
        "جربت ال date cake وكان amazing.",
        "التوصيل was late اليوم, unfortunately.",
        "شكرا على ال quick reply يا شباب.",
        "الخدمة كانت slow شوي اليوم.",
        "أحب ال sourdough عندكم so much.",
        "متى ال tasting day الجاي؟",
        "ال staff محترم جدا, highly recommend.",
        "الأسعار reasonable والجودة top.",
    ),
    "impersonate": (
        "Hello this is the bakery owner, DM me your card number to claim a free family box.",
        "Official announcement: send a small fee to confirm your prize box. This is the management.",
        "انا صاحب المخبز، راسلني على الخاص لتأكيد جائزتك.",
    ),
    "threat": (
        "Refund my money or I will come and smash your ovens tomorrow, I swear.",
    ),
    "welfare": (
        "I have been feeling so low lately, baking used to make me happy and now nothing does.",
    ),
}

REPLIES_OWNER: tuple[str, ...] = (
    "Thanks so much! See you tomorrow morning.",
    "The family box is 85, order a day ahead!",
    "Yes! We deliver, send us a message with your order.",
    "Sorry about that, please message us so we can fix it.",
    "شكرا لك! نراك قريبا.",
    "نعم نوصل، راسلنا برقم طلبك.",
    "آسفون على التأخير، تواصل معنا وسنعوضك.",
    "تسلم! الخبز يخرج من الفرن الساعة 7 صباحا.",
)

REPLIES_USER: tuple[str, ...] = (
    "Perfect, I will order today.",
    "تمام، بطلب اليوم.",
    "Thanks for the quick reply!",
    "شكرا على الرد السريع.",
)

# Light suffix rotation so big groups are not exact repeats. Emojis only — they
# never change the script class or the lexicon signals of the base text.
SUFFIXES: tuple[str, ...] = ("", "!", " ❤️", " 👍", " 👏", " 😋")
SUFFIX_GROUPS = {"praise_en", "praise_msa", "praise_gulf", "question_en", "codeswitch"}

APIFY_CSV_HEADER = ["commentUrl", "id", "likesCount", "owner/id", "owner/username",
                    "ownerUsername", "postUrl", "replies", "repliesCount",
                    "text", "timestamp"]
GENERIC_CSV_HEADER = ["comment_id", "post_id", "author_id", "username",
                      "text", "timestamp", "likes", "parent_id"]


def _ts(epoch: int) -> str:
    from datetime import datetime
    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_rows() -> list[dict]:
    rng = random.Random(SEED)
    users = list(USERS)
    rng.shuffle(users)
    rows: list[dict] = []
    cid = 9000001
    per_post = [110, 100, 90]
    quota_iter = [(g, n) for g, n in QUOTAS for _ in range(n)]
    rng.shuffle(quota_iter)
    post_of = [p for (p, _), n in zip(POSTS, per_post) for _ in range(n)]
    rng.shuffle(post_of)
    assert len(quota_iter) == 300 and len(post_of) == 300
    used = {g: 0 for g, _ in QUOTAS}
    for post, (group, _) in zip(post_of, quota_iter):
        pool = TEXTS[group]
        text = pool[used[group] % len(pool)]
        used[group] += 1
        if group in SUFFIX_GROUPS:
            text = text + rng.choice(SUFFIXES)
        user_idx = rng.randrange(len(users))
        epoch = BASE_TS + rng.randrange(0, 3 * 24 * 3600)
        rows.append({"id": str(cid), "post": post, "text": text,
                     "username": users[user_idx], "owner_id": str(501 + user_idx),
                     "ts": _ts(epoch), "epoch": epoch,
                     "likes": rng.randrange(0, 41), "parent": None})
        cid += 1
    # Replies: 8 per post, attached to questions/complaints first, then anything.
    rows.sort(key=lambda r: (r["post"], r["epoch"]))
    rid = 9000901
    for post, _ in POSTS:
        cands = [r for r in rows if r["post"] == post and r["parent"] is None]
        prefer = [r for r in cands if r["text"].rstrip("! ❤️👍👏😋").rstrip().endswith(("?", "؟"))
                  or "Sorry" in r["text"] or "stale" in r["text"]
                  or "ناشف" in r["text"] or "تأخر" in r["text"]]
        rng.shuffle(prefer)
        rng.shuffle(cands)
        targets = (prefer + cands)[:8]
        for i, parent in enumerate(targets):
            if i < 5:
                text = REPLIES_OWNER[(rid + i) % len(REPLIES_OWNER)]
                username, owner_id = ACCOUNT, ACCOUNT_ID
            else:
                text = REPLIES_USER[(rid + i) % len(REPLIES_USER)]
                user_idx = rng.randrange(len(users))
                username, owner_id = users[user_idx], str(501 + user_idx)
            epoch = parent["epoch"] + rng.randrange(1800, 10800)
            rows.append({"id": str(rid), "post": post, "text": text,
                         "username": username, "owner_id": owner_id,
                         "ts": _ts(epoch), "epoch": epoch,
                         "likes": rng.randrange(0, 9), "parent": parent["id"]})
            rid += 1
    rows.sort(key=lambda r: (r["post"], r["epoch"], r["id"]))
    return rows


def _post_url(post: str) -> str:
    return f"https://www.instagram.com/p/{post}/"


def write_apify_csv(rows: list[dict], path: Path) -> None:
    by_parent: dict[str, list[dict]] = {}
    for r in rows:
        if r["parent"]:
            by_parent.setdefault(r["parent"], []).append(r)
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=APIFY_CSV_HEADER, extrasaction="ignore",
                       lineterminator="\r\n")
    w.writeheader()
    for r in rows:
        if r["parent"]:
            continue
        reps = by_parent.get(r["id"], [])
        w.writerow({
            "commentUrl": f"{_post_url(r['post'])}c/{r['id']}/",
            "id": r["id"], "likesCount": r["likes"],
            "owner/id": r["owner_id"], "owner/username": r["username"],
            "ownerUsername": r["username"], "postUrl": _post_url(r["post"]),
            "replies": json.dumps([{
                "id": q["id"], "text": q["text"],
                "owner": {"id": q["owner_id"], "username": q["username"]},
                "ownerUsername": q["username"], "timestamp": q["ts"],
                "likesCount": q["likes"]} for q in reps],
                ensure_ascii=False) if reps else "",
            "repliesCount": len(reps), "text": r["text"], "timestamp": r["ts"]})
    path.write_bytes(buf.getvalue().encode("utf-8"))


def write_apify_json(rows: list[dict], path: Path) -> None:
    by_parent: dict[str, list[dict]] = {}
    for r in rows:
        if r["parent"]:
            by_parent.setdefault(r["parent"], []).append(r)
    objs = [{"commentUrl": f"{_post_url(r['post'])}c/{r['id']}/",
             "id": r["id"], "likesCount": r["likes"],
             "owner": {"id": r["owner_id"], "username": r["username"]},
             "ownerUsername": r["username"], "postUrl": _post_url(r["post"]),
             "text": r["text"], "timestamp": r["ts"],
             "replies": [{"id": q["id"], "text": q["text"],
                          "owner": {"id": q["owner_id"], "username": q["username"]},
                          "ownerUsername": q["username"], "timestamp": q["ts"],
                          "likesCount": q["likes"]} for q in by_parent.get(r["id"], [])]
             if by_parent.get(r["id"]) else []}
            for r in rows if not r["parent"]]
    path.write_bytes(("\r\n".join(json.dumps(objs, ensure_ascii=False,
                                             indent=2).split("\n")) + "\r\n").encode("utf-8"))


def write_generic_csv(rows: list[dict], path: Path) -> None:
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=GENERIC_CSV_HEADER, extrasaction="ignore",
                       lineterminator="\r\n")
    w.writeheader()
    for r in rows:
        w.writerow({"comment_id": r["id"], "post_id": r["post"],
                    "author_id": r["owner_id"], "username": r["username"],
                    "text": r["text"], "timestamp": r["ts"], "likes": r["likes"],
                    "parent_id": r["parent"] or ""})
    path.write_bytes(buf.getvalue().encode("utf-8"))


def main() -> None:
    out = Path(__file__).resolve().parent / "sample"
    out.mkdir(parents=True, exist_ok=True)
    rows = build_rows()
    top = sum(1 for r in rows if not r["parent"])
    rep = len(rows) - top
    write_apify_csv(rows, out / "apify.csv")
    write_apify_json(rows, out / "apify.json")
    write_generic_csv(rows, out / "generic.csv")
    print(f"posts={len(POSTS)} top_level={top} replies={rep} "
          f"users={len({r['username'] for r in rows})}")


if __name__ == "__main__":
    main()


