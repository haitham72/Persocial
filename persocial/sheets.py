"""Review sheet lifecycle: scoring → judging → ready (→ reviewers notified). The logic is in
Postgres (sheet_advance / sheet_mark_ready) so it runs the same whether a score arrives from
Colab through the Edge Function or from the local worker; these are thin wrappers."""

from __future__ import annotations

from persocial import db


def advance(sheet_id: int) -> str:
    return db.fetch_one("select public.sheet_advance(%s) as s", (sheet_id,))["s"]


def advance_for_post(post_code: str) -> None:
    db.execute("select public.sheets_advance_for_post(%s)", (post_code,))


def mark_ready(sheet_id: int) -> str:
    return db.fetch_one("select public.sheet_mark_ready(%s) as s", (sheet_id,))["s"]


def fail(sheet_id: int, error: str) -> None:
    db.execute("update review_sheets set status='failed' where id=%s", (sheet_id,))
