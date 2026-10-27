"""One judge batch against any OpenAI-compatible endpoint (LM Studio locally, or a cloud
model). Ported from the SocialCompanion demo's judge: short throwaway ids, positional
values, regex salvage of a mangled response, one retry, then 'review' for anything
missing — never a silent keep/hide. Every call is returned with its full request and raw
response so the runner can store it as distillation data."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from dataclasses import dataclass, field

from openai import OpenAI

from persocial.config import settings

# Lenient per-entry salvage. Observed from qwen3.5-4b: entries with the reason dropped and
# closed with "}" instead of "]" — e.g. "6": ["keep", "grievance", 1, 0.9}. Confidence and
# reason are optional here; either bracket closes the entry.
_ENTRY_RE = re.compile(
    r'"(\d+)"\s*:\s*\[\s*"(hide|keep|review)"\s*,\s*"([a-z_]+)"\s*,\s*(\d)'
    r'\s*(?:,\s*([0-9.]+))?\s*(?:,\s*"([^"]*)")?\s*[\]}]')
_clients: dict[str, OpenAI] = {}


@dataclass
class CallRecord:
    request: dict
    response_text: str | None
    parse_status: str                       # ok | salvaged | failed
    latency_ms: int
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None = None


@dataclass
class BatchResult:
    verdicts: dict[str, dict]               # real comment id -> {verdict,category,severity,...}
    calls: list[CallRecord] = field(default_factory=list)


def _client(model_row: dict) -> OpenAI:
    base = model_row["base_url"] or settings().judge_base_url
    key = os.environ.get(model_row["api_key_env"] or "", "") or "lm-studio"
    ck = f"{base}|{key[:6]}"
    if ck not in _clients:
        _clients[ck] = OpenAI(base_url=base, api_key=key, timeout=300)
    return _clients[ck]


def is_local(model_row: dict) -> bool:
    return not model_row["base_url"]


def loaded_local_models() -> set[str]:
    """Model names LM Studio has in memory right now (empty if it isn't reachable)."""
    base = settings().judge_base_url.removesuffix("/v1")
    try:
        with urllib.request.urlopen(f"{base}/api/v0/models", timeout=5) as r:
            return {m["id"] for m in json.load(r)["data"] if m.get("state") == "loaded"}
    except OSError:
        return set()


def ensure_loaded(model_row: dict) -> None:
    """Never let a run JIT-load a local model: LM Studio would load it with whatever thinking
    setting it last had. The operator loads it and turns thinking off by hand first."""
    if is_local(model_row) and model_row["model"] not in loaded_local_models():
        raise ModelNotLoaded(f"{model_row['model']} is not loaded in LM Studio — load it with "
                             f"thinking off, then run again")


class ModelNotLoaded(RuntimeError):
    pass


def _strip(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^<think>.*?</think>", "", raw, flags=re.DOTALL).strip()   # reasoning models
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
    return raw.strip()


def _coerce(entry) -> dict | None:
    if not isinstance(entry, list) or not entry:
        return None
    verdict = str(entry[0]).lower()
    category = str(entry[1]).lower() if len(entry) > 1 else "none"
    try:
        severity = max(0, min(3, int(entry[2]))) if len(entry) > 2 else 0
    except (TypeError, ValueError):
        severity = 0
    try:
        confidence = float(entry[3]) if len(entry) > 3 else None
    except (TypeError, ValueError):
        confidence = None
    reason = str(entry[4]) if len(entry) > 4 else ""
    return {"verdict": verdict if verdict in ("hide", "keep", "review") else "review",
            "category": category, "severity": severity, "confidence": confidence,
            "reason": reason[:200]}


def salvage(raw: str, local_to_real: dict[str, str]) -> dict[str, dict]:
    out = {}
    for lid, verdict, cat, sev, conf, reason in _ENTRY_RE.findall(raw or ""):
        real = local_to_real.get(lid)
        if real:
            out[real] = {"verdict": verdict, "category": cat, "severity": int(sev),
                         "confidence": float(conf) if conf else None, "reason": reason or ""}
    return out


def _one_call(model_row: dict, system_prompt: str, payload: dict,
              local_to_real: dict[str, str], temperature: float = 0.1
              ) -> tuple[dict[str, dict], CallRecord]:
    user = json.dumps(payload, ensure_ascii=False)
    extra = {}
    if model_row.get("disable_thinking"):
        # Measured on LM Studio + qwen3.5-9b (2026-10-20): only reasoning_effort="none" turns
        # reasoning off (0 reasoning tokens). "/no_think", chat_template_kwargs and
        # reasoning_effort="low" were all ignored (~220-260 reasoning tokens on a yes/no
        # question; 5k+ on a 50-comment batch). Don't rely on the LM Studio UI toggle — a
        # model reload resets it.
        extra = {"reasoning_effort": "none"}
    messages = [{"role": "system", "content": system_prompt},
                {"role": "user", "content": user}]
    t0 = time.time()
    try:
        resp = _client(model_row).chat.completions.create(
            model=model_row["model"], messages=messages, temperature=temperature,
            extra_body=extra or None)
        raw = resp.choices[0].message.content or ""
        usage = resp.usage
    except Exception as e:  # noqa: BLE001 — network/server errors become a recorded failure
        return {}, CallRecord({"messages": messages}, None, "failed",
                              int((time.time() - t0) * 1000), error=str(e)[:500])
    rec = CallRecord({"messages": messages}, raw, "ok", int((time.time() - t0) * 1000),
                     usage.prompt_tokens if usage else None,
                     usage.completion_tokens if usage else None)
    out: dict[str, dict] = {}
    try:
        parsed = json.loads(_strip(raw))
        for lid, entry in (parsed.items() if isinstance(parsed, dict) else []):
            real = local_to_real.get(str(lid))
            v = _coerce(entry)
            if real and v:
                out[real] = v
        if not out:
            raise ValueError("no usable entries")
    except (ValueError, TypeError) as e:
        out = salvage(raw, local_to_real)
        rec.parse_status = "salvaged" if out else "failed"
        rec.error = str(e)[:300]
    return out, rec


def judge_batch(model_row: dict, system_prompt: str, items: list[tuple[str, str]],
                account: str, caption: str) -> BatchResult:
    """items: [(real_id, text)]. Real ids never leave this function."""
    local_to_real = {str(i): rid for i, (rid, _) in enumerate(items, start=1)}
    payload = {"account": f"@{account}" if account else "", "post_caption": (caption or "")[:600],
               "comments": {str(i): text[:1500] for i, (_, text) in enumerate(items, start=1)}}
    res = BatchResult({})
    verdicts, rec = _one_call(model_row, system_prompt, payload, local_to_real)
    res.calls.append(rec)
    missing = {k: v for k, v in local_to_real.items() if v not in verdicts}
    if missing and rec.parse_status != "ok" or (missing and len(missing) == len(items)):
        # the base 0.1 would likely reproduce the same broken text; nudge it for the retry
        retry, rec2 = _one_call(model_row, system_prompt, payload, local_to_real, 0.3)
        res.calls.append(rec2)
        verdicts.update({k: v for k, v in retry.items() if k not in verdicts})
    for rid, _ in items:
        verdicts.setdefault(rid, {"verdict": "review", "category": "none", "severity": 2,
                                  "confidence": None, "reason": "judge_error"})
    res.verdicts = verdicts
    return res
