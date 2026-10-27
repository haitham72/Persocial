"""Postgres access: one psycopg 3 pool against the local Supabase database. Raw SQL on
purpose — the schema is owned by supabase/migrations, so there's no second schema
definition (ORM models) to drift from it."""

from __future__ import annotations

import atexit
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from persocial.config import settings

_pool: ConnectionPool | None = None


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            settings().database_url, min_size=1, max_size=10, open=True,
            kwargs={"row_factory": dict_row, "autocommit": False},
        )
        atexit.register(_pool.close)
    return _pool


@contextmanager
def tx() -> Iterator[Any]:
    """A connection inside one transaction: commit on success, rollback on error."""
    with pool().connection() as conn, conn.transaction():
        yield conn


def fetch_all(sql: str, params: Any = None) -> list[dict]:
    with tx() as conn:
        return conn.execute(sql, params).fetchall()


def fetch_one(sql: str, params: Any = None) -> dict | None:
    with tx() as conn:
        return conn.execute(sql, params).fetchone()


def execute(sql: str, params: Any = None) -> int:
    with tx() as conn:
        return conn.execute(sql, params).rowcount
