"""`persocial doctor`: one check per line, one fix per failure."""

from __future__ import annotations

import sys
import urllib.request

from persocial.config import settings
from persocial.local.models import MODEL_IDS, models_cached
from persocial.local.store import default_db_path


def judge_base() -> str:
    return settings().judge_base_url.rstrip("/")


def judge_reachable(base: str | None = None, timeout: float = 5.0) -> bool:
    """True if an OpenAI-compatible endpoint answers (LM Studio or remote)."""
    base = (base or judge_base()).rstrip("/")
    candidates = [base + "/models"]
    if base.endswith("/v1"):
        candidates.append(base[: -len("/v1")] + "/api/v0/models")
    for url in candidates:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                if r.status == 200:
                    return True
        except OSError:
            continue
    return False


def checks() -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    ok = sys.version_info >= (3, 11)
    out.append(("python >= 3.11", ok, "install Python 3.11+ from python.org"))
    try:
        import torch
        import transformers  # noqa: F401

        out.append(("scoring libs (torch, transformers)", True, ""))
    except ImportError:
        out.append(("scoring libs (torch, transformers)", False, "uv sync --all-extras"))
    try:
        import torch

        if torch.cuda.is_available():
            dev = "cuda:" + torch.cuda.get_device_name(0)
        elif torch.backends.mps.is_available():
            dev = "mps (Apple Metal)"
        else:
            dev = "cpu"
        out.append((f"device: {dev}", True, ""))
    except ImportError:
        out.append(("device", False, "uv sync --all-extras"))
    cached, missing = models_cached()
    out.append(("scoring models cached" if cached else f"scoring models missing: {missing}",
                cached, "" if cached else "persocial models pull"))
    base = judge_base()
    up = judge_reachable(base)
    out.append((f"judge endpoint ({base})" if up else f"judge endpoint unreachable ({base})",
                up, "" if up else "load a model in LM Studio (OpenAI-compat server, "
                "thinking off) + set PERSOCIAL_JUDGE_MODEL, or run with --no-judge"))
    db = default_db_path()
    out.append(("store (.persocial/persocial.db)" if db.exists() else "store (empty)",
                True, "" if db.exists() else "persocial run <file> --no-judge"))
    _ = MODEL_IDS
    return out


def main() -> int:
    bad = 0
    for name, ok, fix in checks():
        print(("ok   " if ok else "FAIL ") + name)
        if not ok:
            bad += 1
            print(f"     fix: {fix}")
    return 1 if bad else 0
