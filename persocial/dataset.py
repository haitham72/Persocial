"""Fine-tuning set for a local student judge, built from real judge calls.

One example per stored judge call: the exact system prompt + the exact user payload the
teacher saw, and as the target the best label we have per comment, in trust order:
  human   a reviewer decided (hide/keep; escalate → review)
  agree   ≥2 models labelled it and agree on the verdict
  single  one teacher's verdict
The split is by post (hash of the shortcode), so no post leaks between train and eval.
Each example carries its tiers, so training can filter (e.g. drop calls with only 'single').
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime

from persocial import db
from persocial.config import settings


def _target(labels: list[dict], decision: str | None) -> tuple[list, str]:
    if decision:
        verdict = {"escalate": "review"}.get(decision, decision)
        base = next((lb for lb in labels if lb["verdict"] == verdict), labels[0] if labels else None)
        cat = (base or {}).get("category") or "none"
        sev = (base or {}).get("severity") if base and base["verdict"] == verdict else \
            {"hide": 3, "review": 2, "keep": 0}[verdict]
        return [verdict, cat, sev, 1.0, "human decision"], "human"
    verdicts = Counter(lb["verdict"] for lb in labels)
    top, n = verdicts.most_common(1)[0]
    pick = next(lb for lb in labels if lb["verdict"] == top)
    tier = "agree" if n >= 2 and len(verdicts) == 1 else "single"
    return [top, pick["category"] or "none", pick["severity"] or 0,
            round(pick["confidence"] or 0.0, 2), (pick["reason"] or "")[:60]], tier


def export(name: str | None = None, eval_share: float = 0.1, min_tier: str = "single") -> dict:
    name = name or datetime.now(UTC).strftime("judge-%Y%m%d-%H%M")
    out_dir = settings().datasets_root / name
    out_dir.mkdir(parents=True, exist_ok=True)
    prompts = {r["version"]: r["system_prompt"] for r in db.fetch_all("select version, system_prompt from prompts")}
    calls = db.fetch_all("""select id, prompt, post_code, user_payload, item_ids from judge_calls
                            where parse_status in ('ok', 'salvaged') order by id""")
    rank = {"single": 0, "agree": 1, "human": 2}
    stats: Counter = Counter()
    with open(out_dir / "train.jsonl", "w", encoding="utf-8") as tr, \
         open(out_dir / "eval.jsonl", "w", encoding="utf-8") as ev:
        for call in calls:
            ids = call["item_ids"]
            labels = {}
            for r in db.fetch_all("""select ig_id, model, verdict, category, severity, confidence, reason
                                     from judge_labels where ig_id = any(%s)""", (ids,)):
                labels.setdefault(r["ig_id"], []).append(r)
            decisions = {r["ig_id"]: r["decision"] for r in db.fetch_all(
                "select ig_id, decision from comments where ig_id = any(%s)", (ids,))}
            target, tiers = {}, []
            for local, ig in enumerate(ids, start=1):
                if ig not in labels and not decisions.get(ig):
                    break
                t, tier = _target(labels.get(ig, []), decisions.get(ig))
                target[str(local)] = t
                tiers.append(tier)
            if len(target) != len(ids) or min(rank[t] for t in tiers) < rank[min_tier]:
                stats["skipped"] += 1
                continue
            split = "eval" if int(hashlib.md5((call["post_code"] or "").encode()).hexdigest(), 16) % 100 \
                < eval_share * 100 else "train"
            ex = {"messages": [
                    {"role": "system", "content": prompts.get(call["prompt"], "")},
                    {"role": "user", "content": call["user_payload"].removesuffix(" /no_think")},
                    {"role": "assistant", "content": json.dumps(target, ensure_ascii=False)}],
                  "meta": {"call_id": call["id"], "post": call["post_code"], "prompt": call["prompt"],
                           "tiers": dict(Counter(tiers))}}
            (ev if split == "eval" else tr).write(json.dumps(ex, ensure_ascii=False) + "\n")
            stats[split] += 1
            stats.update(f"tier:{t}" for t in tiers)
    summary = {"name": name, "path": str(out_dir), "calls": len(calls), **stats}
    (out_dir / "stats.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary
