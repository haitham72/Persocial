"""Sentiment + emotion scoring. SELF-CONTAINED on purpose: scripts/build_colab_notebook.py
embeds this file verbatim into colab/score_csv.ipynb, so it may import only the stdlib,
torch, transformers and pandas — never anything from `persocial`.

Matches the historical scorer (sentiment_fast_hybrid_local_v2.py) so new scores are
comparable with earlier runs: same models, same @user/http
preprocessing, all sentiment labels ranked, emotions kept only above 0.45.
"""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime

MODEL_VERSION = "persocial-v1"
SENTIMENT_MODEL = "cardiffnlp/twitter-xlm-roberta-base-sentiment-multilingual"
EMOTION_MODEL = "AnasAlokla/multilingual_go_emotions"
EMOTION_THRESHOLD = 0.45
MAX_LENGTH = 512
DEFAULT_BATCH = {"cuda": 128, "mps": 48, "cpu": 64}   # MPS stalls on large batches

SCORE_COLUMNS = ["sentiment_fast", "emotions_fast", "updated_at", "model_version"]


def preprocess(text: str) -> str:
    t = re.sub(r"(?<!\S)@\S+", "@user", text or "")
    return re.sub(r"http\S*", "http", t)


def resolve_device(prefer: str = "auto"):
    import torch
    if prefer in ("cuda", "auto") and torch.cuda.is_available():
        return "cuda", 0, torch.float16, torch.cuda.get_device_name(0)
    if prefer in ("mps", "auto") and torch.backends.mps.is_available():
        # fp32 on Metal: fp16 kernels fall back silently and end up slower
        return "mps", "mps", torch.float32, "Apple Metal"
    return "cpu", -1, torch.float32, "CPU"


class Scorer:
    def __init__(self, device: str = "auto", batch_size: int = 0):
        from transformers import AutoConfig, pipeline
        self.device, pipe_device, dtype, self.device_name = resolve_device(device)
        self.batch_size = batch_size or DEFAULT_BATCH[self.device]
        common = {"device": pipe_device, "torch_dtype": dtype, "truncation": True,
                  "max_length": MAX_LENGTH}
        self.sent = pipeline("text-classification", model=SENTIMENT_MODEL, top_k=None, **common)
        n_emo = AutoConfig.from_pretrained(EMOTION_MODEL).num_labels
        self.emo = pipeline("text-classification", model=EMOTION_MODEL, top_k=n_emo, **common)

    @property
    def runner(self) -> str:
        return f"{self.device}:{self.device_name}"

    def score(self, texts: list[str], on_progress=None) -> list[tuple[list[dict], list[dict]]]:
        """[(sentiment ranked, emotions above threshold)] per text, same order."""
        clean = [preprocess(t) or " " for t in texts]
        out: list[tuple[list[dict], list[dict]]] = []
        for start in range(0, len(clean), self.batch_size):
            batch = clean[start:start + self.batch_size]
            s_res = self.sent(batch, batch_size=len(batch))
            e_res = self.emo(batch, batch_size=len(batch))
            for s_row, e_row in zip(s_res, e_res):
                sent = sorted(({"label": r["label"], "score": round(float(r["score"]), 4)}
                               for r in s_row), key=lambda x: x["score"], reverse=True)
                emo = sorted(({"label": r["label"], "score": round(float(r["score"]), 4)}
                              for r in e_row if r["score"] >= EMOTION_THRESHOLD),
                             key=lambda x: x["score"], reverse=True)
                out.append((sent, emo))
            if on_progress:
                on_progress(min(start + self.batch_size, len(clean)), len(clean))
        return out


def score_csv(in_path: str, out_path: str, device: str = "auto", batch_size: int = 0) -> dict:
    """Colab / CLI entry: read an exported CSV, fill the score columns for rows that lack
    them, write the result. Every other column (incl. claim_id) passes through untouched,
    so the output imports straight back through the normal upload."""
    import pandas as pd
    df = pd.read_csv(in_path, dtype=str, keep_default_na=False)
    for col in SCORE_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    todo = df.index[df["sentiment_fast"].str.strip() == ""].tolist()
    t0 = time.time()
    if todo:
        scorer = Scorer(device, batch_size)
        print(f"scoring {len(todo)} comments on {scorer.runner}")

        def progress(done, total):
            print(f"  {done}/{total}  {done / max(time.time() - t0, 1e-6):.0f}/s", flush=True)

        results = scorer.score(df.loc[todo, "text"].tolist(), on_progress=progress)
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        for idx, (sent, emo) in zip(todo, results):
            df.at[idx, "sentiment_fast"] = json.dumps(sent, ensure_ascii=False)
            df.at[idx, "emotions_fast"] = json.dumps(emo, ensure_ascii=False)
            df.at[idx, "updated_at"] = now
            df.at[idx, "model_version"] = MODEL_VERSION
    df.to_csv(out_path, index=False, encoding="utf-8")
    return {"rows": len(df), "scored": len(todo), "seconds": round(time.time() - t0, 1)}
