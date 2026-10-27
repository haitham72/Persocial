"""`persocial models pull`: pre-download the HF scoring models.

First `persocial run` without cached models prints the download size (~1.1 GB) and
points here instead of stalling mid-pipeline.
"""

from __future__ import annotations

from persocial.config import settings

MODEL_IDS = (settings().sentiment_model, settings().emotion_model)


def models_cached() -> tuple[bool, str]:
    """(all_cached, missing_ids). Offline-safe: an unreadable cache counts as missing."""
    try:
        from huggingface_hub import scan_cache_dir

        cached = {r.repo_id for r in scan_cache_dir().repos}
    except Exception:  # noqa: BLE001 — no cache access means "not cached"
        return False, " ".join(MODEL_IDS)
    missing = [m for m in MODEL_IDS if m not in cached]
    return (not missing, " ".join(missing))


def pull() -> dict:
    from huggingface_hub import snapshot_download

    out = {}
    for repo in MODEL_IDS:
        path = snapshot_download(repo)
        print(f"cached {repo} -> {path}")
        out[repo] = path
    return out
