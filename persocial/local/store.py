"""Tier 1 local store: SQLite in ./.persocial/persocial.db.

Implements only the slice of the Tier 2 Postgres interface the headless pipeline
needs: ingest upsert (dedup by ig_id), unscored/unjudged scans, score + judgment
writes. The scorer, select, judge client and policy are reused unchanged; this
module adapts at the store boundary (review.md G3.1).
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from persocial.ingest.parsers import Parsed

SCHEMA = """
create table if not exists comments (
  ig_id          text primary key,
  post_code      text not null default '',
  post_url       text not null default '',
  username       text not null default '',
  owner_id       text not null default '',
  text           text not null default '',
  text_norm      text not null default '',
  script         text not null default 'other',
  created_at     text,
  like_count     integer,
  parent_id      text not null default '',
  sentiment      text,
  sentiment_score real,
  sentiment_full text,
  emotion        text,
  emotions_full  text,
  scored_at      text,
  model_version  text,
  signals        text not null default '',
  selection      text not null default '',
  verdict        text not null default '',
  category       text not null default '',
  severity       integer,
  confidence     real,
  reason         text not null default '',
  welfare        integer not null default 0,
  judged_at      text,
  source_file    text not null default ''
);
create table if not exists files (
  sha256      text primary key,
  filename    text not null,
  rows        integer not null default 0,
  inserted    integer not null default 0,
  imported_at text not null
);
"""


def default_db_path() -> Path:
    return Path.cwd() / ".persocial" / "persocial.db"


def _utcnow() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


class Store:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    def upsert_parsed(self, parsed: Parsed, filename: str, digest: str) -> dict:
        """Insert new comments, ignore repeats. Re-running a file adds 0 rows."""
        inserted = 0
        with self.conn:
            for c in parsed.comments:
                sent = c.sentiment or []
                emo = c.emotions or []
                cur = self.conn.execute(
                    """insert into comments
                       (ig_id, post_code, username, owner_id, text, text_norm, script,
                        created_at, like_count, parent_id,
                        sentiment, sentiment_score, sentiment_full,
                        emotion, emotions_full, scored_at, model_version, source_file)
                       values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       on conflict (ig_id) do nothing""",
                    (c.ig_id, c.post_code, c.username or "", c.owner_id or "", c.text,
                     c.text_norm, c.script,
                     c.created_at.isoformat() if c.created_at else None, c.like_count,
                     c.parent_ig_id or "",
                     sent[0]["label"] if sent else None,
                     float(sent[0]["score"]) if sent else None,
                     _dump(sent) if sent else None,
                     emo[0]["label"] if emo else None,
                     _dump(emo) if sent else None,
                     c.scored_at.isoformat() if c.scored_at else None,
                     c.model_version, filename),
                )
                inserted += cur.rowcount
            self.conn.execute(
                """insert into files (sha256, filename, rows, inserted, imported_at)
                   values (?,?,?,?,?)
                   on conflict (sha256) do update set imported_at=excluded.imported_at""",
                (digest, filename, len(parsed.comments), inserted, _utcnow()),
            )
        return {"inserted": inserted, "existing": len(parsed.comments) - inserted}

    def unscored(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "select * from comments where sentiment is null")]

    def unjudged(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "select * from comments where verdict is null or verdict = ''")]

    def all_comments(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "select * from comments order by post_code, ig_id")]

    def update_score(self, ig_id: str, sent: list, emo: list, model_version: str) -> None:
        with self.conn:
            self.conn.execute(
                """update comments set sentiment=?, sentiment_score=?, sentiment_full=?,
                     emotion=?, emotions_full=?, scored_at=?, model_version=? where ig_id=?""",
                (sent[0]["label"], float(sent[0]["score"]), _dump(sent),
                 emo[0]["label"] if emo else None, _dump(emo) if emo else "[]",
                 _utcnow(), model_version, ig_id),
            )

    def update_judgment(self, ig_id: str, *, selection: str, signals: list[str],
                        verdict: str, category: str, severity: int,
                        confidence: float | None, reason: str, welfare: bool) -> None:
        with self.conn:
            self.conn.execute(
                """update comments set selection=?, signals=?, verdict=?, category=?,
                     severity=?, confidence=?, reason=?, welfare=?, judged_at=?
                   where ig_id=?""",
                (selection, ",".join(signals), verdict, category, severity, confidence,
                 reason or "", 1 if welfare else 0, _utcnow(), ig_id),
            )

    def stats(self) -> dict:
        row = self.conn.execute(
            """select count(*) n,
                      sum(sentiment is not null) scored,
                      sum(verdict <> '') judged,
                      count(distinct post_code) posts from comments""").fetchone()
        return {"comments": row["n"], "scored": row["scored"] or 0,
                "judged": row["judged"] or 0, "posts": row["posts"] or 0}


def _dump(obj) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
