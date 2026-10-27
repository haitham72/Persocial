"""ingest_file(): Python entry for uploads through the persocial API and for the backfill.

The merge itself lives in Postgres (ingest_begin → ingest_*_chunk → ingest_finish, see
supabase/migrations/*_rpc.sql) so the web app, Colab and this service share one
implementation. This module only parses, chunks, and calls those functions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

import psycopg
from psycopg.types.json import Jsonb

from persocial import db
from persocial.config import settings
from persocial.ingest.parsers import CommentRow, MetricRow, parse_file

CHUNK = 5000


class UnknownPostsError(ValueError):
    """Comments for posts we've never seen and no account to attach them to."""

    def __init__(self, codes: list[str]):
        super().__init__(f"unknown post(s) {', '.join(codes)} — pick the account they belong to")
        self.codes = codes


@dataclass
class IngestResult:
    batch_id: int
    source: str
    filename: str
    duplicate_file: bool = False
    rows_total: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_scored: int = 0
    rows_rejected: int = 0
    rejects: list[dict] = field(default_factory=list)
    posts: list[str] = field(default_factory=list)
    sheet_ids: list[int] = field(default_factory=list)
    claim: dict | None = None
    image_urls: dict[str, str] = field(default_factory=dict)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


def comment_json(c: CommentRow) -> dict:
    return {"ig_id": c.ig_id, "post_code": c.post_code, "parent_ig_id": c.parent_ig_id,
            "author_id": c.owner_id, "author": c.username, "text": c.text,
            "created_at": _iso(c.created_at), "like_count": c.like_count,
            "repeat_commenter": c.repeat_commenter, "sentiment": c.sentiment,
            "emotions": c.emotions, "scored_at": _iso(c.scored_at),
            "model_version": c.model_version}


def metric_json(m: MetricRow) -> dict:
    d = asdict(m)
    d["posted_at"] = _iso(m.posted_at)
    return d


def _rpc(conn, fn: str, *args) -> dict:
    ph = ", ".join(["%s"] * len(args))
    row = conn.execute(f"select public.{fn}({ph}) as r", args).fetchone()
    return row["r"]


def ingest_file(filename: str, data: bytes, *, account_hint: str | None = None,
                create_sheets: bool = True) -> IngestResult:
    digest = sha256(data)
    parsed = parse_file(filename, data)
    meta = {"account": account_hint, "reported_comment_count": parsed.reported_comment_count,
            "rows_total": parsed.rows_total, "rows_rejected": len(parsed.rejects),
            "reject_note": "; ".join(f"line {r['line']}: {r['reason']}" for r in parsed.rejects[:20])
                           or None,
            "captured_at": _iso(parsed.captured_at), "uploaded_by": "persocial"}

    with db.tx() as conn:
        begin = _rpc(conn, "ingest_begin", parsed.source, filename, digest, Jsonb(meta))
    res = IngestResult(batch_id=begin["upload_id"], source=parsed.source, filename=filename,
                       rows_total=parsed.rows_total, rows_rejected=len(parsed.rejects),
                       rejects=parsed.rejects[:50])
    if begin["duplicate"]:
        res.duplicate_file = True
        return res

    raw_dir = settings().storage_root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    ext = ".json" if filename.lower().endswith(".json") else ".csv"
    (raw_dir / f"{digest}{ext}").write_bytes(data)

    try:
        with db.tx() as conn:      # all chunks in one transaction: a file lands whole or not at all
            if parsed.source == "post_metrics_csv":
                captured = parsed.captured_at or datetime.now(UTC)
                rows = [metric_json(m) for m in parsed.metrics]
                for i in range(0, len(rows), CHUNK):
                    out = _rpc(conn, "ingest_metrics_chunk", res.batch_id,
                               Jsonb(rows[i:i + CHUNK]), captured)
                    res.image_urls.update(out["image_urls"])
                res.posts = sorted({m.code for m in parsed.metrics})
            else:
                rows = [comment_json(c) for c in parsed.comments]
                for i in range(0, len(rows), CHUNK):
                    _rpc(conn, "ingest_comments_chunk", res.batch_id, Jsonb(rows[i:i + CHUNK]),
                         account_hint)
                res.posts = sorted({c.post_code for c in parsed.comments})
            fin = _rpc(conn, "ingest_finish", res.batch_id, create_sheets)
    except psycopg.errors.NoDataFound as e:               # raised as 'unknown_posts:a,b'
        msg = str(e).split("unknown_posts:", 1)[-1].split("\n", 1)[0]
        db.execute("delete from uploads where id=%s", (res.batch_id,))
        raise UnknownPostsError([c for c in msg.split(",") if c]) from None
    except Exception:
        db.execute("delete from uploads where id=%s", (res.batch_id,))
        raise

    res.rows_inserted, res.rows_updated = fin["rows_inserted"], fin["rows_existing"]
    res.rows_scored, res.sheet_ids = fin["rows_scored"], fin["sheet_ids"]
    if res.image_urls:
        from persocial import media
        media.fetch_thumbnails(res.image_urls)
    return res


def preview(rows: list[CommentRow]) -> list[dict]:
    with db.tx() as conn:
        return _rpc(conn, "preview_comments",
                    Jsonb([{"p": c.post_code, "i": c.ig_id} for c in rows]))


def dumps(res: IngestResult) -> str:
    return json.dumps(asdict(res), default=str)
