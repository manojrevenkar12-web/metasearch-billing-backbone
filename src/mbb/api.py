"""A small read-only API over the backbone's state: close status, checks, invoices, certified metrics, ask."""

from __future__ import annotations

from datetime import date

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


class Question(BaseModel):
    text: str
    today: date = date(2026, 11, 10)


def create_app(world: str, state: str, settings_path: str = "config/pipeline.toml") -> FastAPI:
    from .metrics.ask import answer, reader_for
    from .pipeline.control import ControlStore
    from .pipeline.warehouse import Warehouse

    import os

    wh = Warehouse(state)
    control = ControlStore.postgres() if os.environ.get("MBB_CONTROL_DSN") else ControlStore.duckdb(wh.con)
    app = FastAPI(title="metasearch billing backbone", version="1.0")

    @app.get("/api/health")
    def health() -> dict:
        (runs,) = control.query("select count(*) from run_log")[0]
        return {"ok": True, "runs": runs}

    @app.get("/api/invoices")
    def invoices() -> list[dict]:
        cols = ["doc_id", "partner_id", "month", "kind", "version", "currency", "clicks", "amount_minor",
                "issued_at", "open_checks"]
        return [dict(zip(cols, r)) for r in control.register()]

    @app.get("/api/checks")
    def checks(status: str = "fail", limit: int = 200) -> list[dict]:
        if status not in ("pass", "fail"):
            raise HTTPException(400, "status is pass or fail")
        rows = control.query(
            """select as_of, check_name, scope, value, threshold, blocking, detail from check_result
               where status = %s order by as_of desc, check_name limit %s""", (status, min(limit, 1000)))
        return [dict(zip(["as_of", "check", "scope", "value", "threshold", "blocking", "detail"], r)) for r in rows]

    @app.get("/api/metrics")
    def metrics() -> dict:
        _, catalog = reader_for(wh)
        return {k: {"label": m["label"], "unit": m["unit"], "dimensions": list(m["dimensions"])}
                for k, m in catalog.metrics.items()}

    @app.post("/api/ask")
    def ask(q: Question) -> dict:
        reader, catalog = reader_for(wh)

        def query(sql: str, params: list):
            if "invoice_register" in sql:
                return control.query(sql.replace("?", "%s"), params)
            return wh.q(sql, params)
        return answer(q.text, reader, catalog, query, q.today)

    return app
