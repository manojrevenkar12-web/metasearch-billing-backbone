"""The control store: which files were loaded, every check result, every run and every invoice document.

It is written in plain SQL that runs unchanged on PostgreSQL (production) and DuckDB (tests, the evaluation).
Invoice documents are only ever inserted: a change after issue is a new adjustment document.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

DDL = [
    """create table if not exists file_ledger (
        path text primary key, object_id text not null, sha256 text, rows_loaded bigint not null,
        status text not null, seen_at timestamp with time zone not null, detail text)""",
    """create table if not exists run_log (
        run_id text primary key, variant text not null, as_of timestamp with time zone not null,
        files_loaded bigint not null, rows_loaded bigint not null, models_built bigint not null,
        blocking_failures bigint not null, invoices_issued bigint not null)""",
    """create table if not exists check_result (
        run_id text not null, as_of timestamp with time zone not null, check_name text not null,
        scope text not null, status text not null, value double precision, threshold double precision,
        blocking boolean not null, detail text)""",
    """create table if not exists invoice_register (
        doc_id text primary key, partner_id text not null, month text not null, kind text not null,
        version integer not null, currency text not null, clicks bigint not null, amount_minor bigint not null,
        issued_at timestamp with time zone not null, open_checks text, basis text)""",
    """create table if not exists alert_log (
        raised_at timestamp with time zone not null, check_name text not null, scope text not null,
        detail text, primary key (check_name, scope))""",
]


@dataclass
class ControlStore:
    conn: object
    kind: str  # "duckdb" or "postgres"

    @classmethod
    def duckdb(cls, con) -> "ControlStore":
        s = cls(con, "duckdb")
        s.init()
        return s

    @classmethod
    def postgres(cls, dsn: str | None = None, schema: str | None = None) -> "ControlStore":
        import psycopg

        conn = psycopg.connect(dsn or os.environ["MBB_CONTROL_DSN"], autocommit=True)
        if schema:
            conn.execute(f'create schema if not exists "{schema}"')
            conn.execute(f'set search_path to "{schema}"')
        s = cls(conn, "postgres")
        s.init()
        return s

    def init(self) -> None:
        for ddl in DDL:
            self.execute(ddl)

    def _sql(self, sql: str) -> str:
        return sql.replace("%s", "?") if self.kind == "duckdb" else sql

    def execute(self, sql: str, params: tuple | list = ()) -> None:
        self.conn.execute(self._sql(sql), params)

    def executemany(self, sql: str, rows: list[tuple]) -> None:
        if not rows:
            return
        if self.kind == "duckdb":
            self.conn.executemany(self._sql(sql), rows)
        else:
            with self.conn.cursor() as cur:
                cur.executemany(sql, rows)

    def query(self, sql: str, params: tuple | list = ()) -> list[tuple]:
        if self.kind == "duckdb":
            return self.conn.execute(self._sql(sql), params).fetchall()
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    # ---------------------------------------------------------------- file ledger
    def ledger(self) -> dict[str, tuple[str, str, str]]:
        return {p: (o, h, s) for p, o, h, s in self.query("select path, object_id, sha256, status from file_ledger")}

    def loaded_hashes(self) -> set[str]:
        return {h for (h,) in self.query("select sha256 from file_ledger where status = 'loaded' and sha256 is not null")}

    def record_file(self, path: str, object_id: str, sha: str | None, rows: int, status: str, at: datetime,
                    detail: str = "") -> None:
        self.execute(
            """insert into file_ledger (path, object_id, sha256, rows_loaded, status, seen_at, detail)
               values (%s, %s, %s, %s, %s, %s, %s)
               on conflict (path) do update set object_id = excluded.object_id, sha256 = excluded.sha256,
                 rows_loaded = excluded.rows_loaded, status = excluded.status, seen_at = excluded.seen_at,
                 detail = excluded.detail""",
            (path, object_id, sha, rows, status, at, detail))

    def record_files(self, rows: list[tuple]) -> None:
        self.executemany(
            """insert into file_ledger (path, object_id, sha256, rows_loaded, status, seen_at, detail)
               values (%s, %s, %s, %s, %s, %s, %s)
               on conflict (path) do update set object_id = excluded.object_id, sha256 = excluded.sha256,
                 rows_loaded = excluded.rows_loaded, status = excluded.status, seen_at = excluded.seen_at,
                 detail = excluded.detail""", rows)

    # ---------------------------------------------------------------- checks, runs, alerts
    def record_checks(self, run_id: str, as_of: datetime, results: list) -> None:
        self.executemany(
            """insert into check_result (run_id, as_of, check_name, scope, status, value, threshold, blocking, detail)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            [(run_id, as_of, r.name, r.scope, r.status, r.value, r.threshold, r.blocking, r.detail) for r in results])
        failing = [r for r in results if r.status == "fail"]
        known = {(c, s) for c, s in self.query("select check_name, scope from alert_log")}
        self.executemany("insert into alert_log (raised_at, check_name, scope, detail) values (%s, %s, %s, %s)",
                         [(as_of, r.name, r.scope, r.detail) for r in failing if (r.name, r.scope) not in known])

    def record_run(self, run_id: str, variant: str, as_of: datetime, files: int, rows: int, models: int,
                   blocking: int, issued: int) -> None:
        self.execute(
            """insert into run_log (run_id, variant, as_of, files_loaded, rows_loaded, models_built,
               blocking_failures, invoices_issued) values (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (run_id, variant, as_of, files, rows, models, blocking, issued))

    # ---------------------------------------------------------------- invoices
    def documents(self, partner_id: str, month: str) -> list[tuple]:
        return self.query(
            """select doc_id, kind, version, clicks, amount_minor, issued_at from invoice_register
               where partner_id = %s and month = %s order by version""", (partner_id, month))

    def issue(self, doc_id: str, partner_id: str, month: str, kind: str, version: int, currency: str, clicks: int,
              amount: int, at: datetime, open_checks: str, basis: str) -> None:
        self.execute(
            """insert into invoice_register (doc_id, partner_id, month, kind, version, currency, clicks,
               amount_minor, issued_at, open_checks, basis) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (doc_id, partner_id, month, kind, version, currency, clicks, amount, at, open_checks, basis))

    def register(self) -> list[tuple]:
        return self.query(
            """select doc_id, partner_id, month, kind, version, currency, clicks, amount_minor, issued_at, open_checks
               from invoice_register order by partner_id, month, version""")
