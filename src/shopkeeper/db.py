"""Database access: a small connection pool over Postgres.

A pool (rather than connect-per-call) keeps the long-running cashier responsive
and transparently recovers if the database restarts.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import load_settings

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    """Lazily create the process-wide connection pool."""
    global _pool
    if _pool is None:
        settings = load_settings()
        _pool = ConnectionPool(
            settings.database_url,
            min_size=1,
            max_size=4,
            kwargs={"row_factory": dict_row},
            open=True,
        )
    return _pool


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    """Borrow a connection from the pool for the duration of the block."""
    with get_pool().connection() as conn:
        yield conn


def ping() -> bool:
    """Return True if the database answers a trivial query."""
    with connection() as conn:
        conn.execute("SELECT 1")
    return True


def close_pool() -> None:
    """Close the pool (call on shutdown)."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
