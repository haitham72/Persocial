"""Scoring leases. A lease is three columns on posts (claimed_by / claimed_at /
claim_expires_at), handed out by the SQL functions claim_posts / claim_comments /
submit_scores / release_claim — the same calls the Colab notebook makes through the
colab-api Edge Function. This module adds the local-GPU loop and the offline CSV export."""

from __future__ import annotations

import csv
import io

from psycopg.types.json import Jsonb

from persocial import db

EXPORT_HEADER = ["id", "owner_id", "username", "text", "created_at", "postID", "Spam"]


def _rpc(sql: str, args: tuple):
    return db.fetch_one(f"select {sql} as r", args)["r"]


def pending(search: str | None = None) -> list[dict]:
    return _rpc("public.pending_scoring(%s)", (search,))


def claim(n: int = 1, runner: str = "colab", post_codes: list[str] | None = None) -> list[dict]:
    """[{post_code, n_unscored, expires_at}] — posts leased to this runner."""
    return _rpc("public.claim_posts(%s, %s, %s)", (post_codes, n, runner))


def comments(post_code: str, limit: int = 5000) -> list[dict]:
    return _rpc("public.claim_comments(%s, %s)", (post_code, limit))


def submit(post_code: str, rows: list[dict], runner: str) -> dict:
    return _rpc("public.submit_scores(%s, %s, %s)", (post_code, Jsonb(rows), runner))


def release(post_code: str) -> bool:
    return _rpc("public.release_claim(%s)", (post_code,))


def csv_bytes(post_code: str) -> bytes:
    """Unscored comments of a post as a comments CSV — score it anywhere, upload it back."""
    rows = _rpc("public.claim_export(%s)", (post_code,))
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=EXPORT_HEADER, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


def score_locally(scorer, *, post_codes: list[str] | None = None, save_every: int = 5000,
                  on_progress=None) -> dict | None:
    """Same loop as the Colab notebook: lease a post → score its unscored comments in
    save_every chunks (each submit is a save point that keeps the lease alive) → the lease
    is released when nothing is left."""
    runner = f"local:{scorer.runner}"
    leased = claim(1, runner, post_codes)
    if not leased:
        return None
    code = leased[0]["post_code"]
    done = 0
    try:
        while True:
            chunk = comments(code, save_every)
            if not chunk:
                break
            results = scorer.score([c["text"] for c in chunk])
            out = submit(code, [{"ig_id": c["ig_id"], "sentiment": s, "emotions": e}
                                for c, (s, e) in zip(chunk, results)], runner)
            done += out["written"]
            if on_progress:
                on_progress(done, leased[0]["n_unscored"])
            if out["remaining"] == 0:
                break
    except Exception:
        release(code)
        raise
    return {"post_code": code, "scored": done}
