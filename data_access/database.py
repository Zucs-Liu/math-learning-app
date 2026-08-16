"""Shared SQLite/Neon connection adapter.

This module only opens connections and normalizes SQL placeholders. Schema
creation and application queries intentionally remain in ``app.py``.
"""

import sqlite3
import sys

import streamlit as st

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool
except ImportError:
    psycopg = None
    ConnectionPool = None
    dict_row = None


@st.cache_resource(show_spinner=False)
def postgres_pool(database_url):
    if ConnectionPool is None:
        raise RuntimeError("公開版需要安裝 psycopg[pool]。")
    return ConnectionPool(
        conninfo=database_url,
        min_size=1,
        max_size=10,
        timeout=15,
        max_lifetime=900,
        max_idle=300,
        reconnect_timeout=30,
        check=ConnectionPool.check_connection,
        kwargs={"row_factory": dict_row},
    )


class DatabaseConnection:
    """Context manager exposing one query interface for SQLite and Postgres."""

    def __init__(self, database_url, db_file):
        self.database_url = database_url
        self.db_file = db_file
        self.use_postgres = bool(database_url)
        self.pool_context = None
        self.connection = None

    def _open_postgres_connection(self):
        self.pool_context = postgres_pool(self.database_url).connection()
        self.connection = self.pool_context.__enter__()

    def __enter__(self):
        if self.use_postgres:
            self._open_postgres_connection()
        else:
            self.connection = sqlite3.connect(self.db_file, timeout=10)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA foreign_keys=ON")
        return self

    def __exit__(self, error_type, error, traceback):
        if self.use_postgres:
            return self.pool_context.__exit__(error_type, error, traceback)
        if error_type:
            self.connection.rollback()
        else:
            self.connection.commit()
        self.connection.close()

    def execute(self, sql, parameters=()):
        if self.use_postgres:
            if sql == "BEGIN IMMEDIATE":
                return self.connection.execute("BEGIN")
            sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO")
            if "INSERT INTO settings" in sql and "registration_enabled" in sql and "ON CONFLICT" not in sql:
                sql += " ON CONFLICT(key) DO NOTHING"
            sql = sql.replace("?", "%s")
            try:
                return self.connection.execute(sql, parameters)
            except psycopg.OperationalError:
                # Neon may terminate a stale connection while waking. Retrying
                # a read is safe; writes are deliberately never replayed.
                if not sql.lstrip().upper().startswith("SELECT"):
                    raise
                self.pool_context.__exit__(*sys.exc_info())
                self._open_postgres_connection()
                return self.connection.execute(sql, parameters)
        return self.connection.execute(sql, parameters)

    def executescript(self, script):
        if self.use_postgres:
            for statement in script.split(";"):
                if statement.strip():
                    self.connection.execute(statement)
        else:
            self.connection.executescript(script)
