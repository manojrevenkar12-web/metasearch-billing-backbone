"""mbb: the command line the schedulers call.

    mbb world   --config config/world.toml --out data/dev
    mbb load    --world data/dev --state data/dev/warehouse.duckdb --as-of 2026-10-02T06:00Z
    mbb build   ... ; mbb check ... ; mbb invoice ...      (the four steps, in order)
    mbb run     ...                                       (all four)
    mbb schedule --world data/dev --state ... [--until 2026-11-10T06:00Z]
    mbb ask "billed clicks by brand last month" --state ...
    mbb serve   --state ... --port 8000
    mbb trino-sql                                          (the models in Trino's dialect)

State is a DuckDB file. The control store is the same file, or PostgreSQL when MBB_CONTROL_DSN is set.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path


def _ts(s: str) -> datetime:
    if s in ("", "now"):
        from datetime import timezone

        return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _backbone(a):
    from .pipeline.control import ControlStore
    from .pipeline.run import Backbone
    from .pipeline.settings import Settings
    from .pipeline.warehouse import Warehouse

    wh = Warehouse(a.state)
    control = ControlStore.postgres() if os.environ.get("MBB_CONTROL_DSN") else ControlStore.duckdb(wh.con)
    return Backbone(a.world, Settings.load(a.settings), warehouse=wh, control=control)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mbb")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("world", help="generate a simulated world")
    w.add_argument("--config", default="config/world.toml")
    w.add_argument("--out", default="data/dev")
    for name in ("load", "build", "check", "invoice", "run", "schedule", "ask", "serve"):
        p = sub.add_parser(name)
        p.add_argument("--world", default="data/dev")
        p.add_argument("--state", default="data/dev/warehouse.duckdb")
        p.add_argument("--settings", default="config/pipeline.toml")
        if name in ("load", "build", "check", "invoice", "run"):
            p.add_argument("--as-of", required=True, type=_ts)
        if name == "schedule":
            p.add_argument("--until", type=_ts)
        if name == "ask":
            p.add_argument("question")
            p.add_argument("--today", type=date.fromisoformat, default=date(2026, 11, 10))
            p.add_argument("--claude", action="store_true", help="let Claude read the question (needs an API key)")
        if name == "serve":
            p.add_argument("--port", type=int, default=8000)
    sub.add_parser("trino-sql", help="print the models in Trino's SQL dialect")
    a = ap.parse_args(argv)

    if a.cmd == "world":
        from .world.sim import generate

        generate(a.config, a.out)
        print(f"world written to {a.out}")
        return 0
    if a.cmd == "trino-sql":
        from .trino import transpile_models

        for name, sql in transpile_models():
            print(f"-- {name}\n{sql};\n")
        return 0
    if a.cmd == "serve":
        import uvicorn

        from .api import create_app

        uvicorn.run(create_app(a.world, a.state, a.settings), host="0.0.0.0", port=a.port)
        return 0
    Path(a.state).parent.mkdir(parents=True, exist_ok=True)
    b = _backbone(a)
    if a.cmd == "load":
        r = b.load(a.as_of)
        print(json.dumps({"files": r.files, "rows": r.rows, "waiting": r.waiting, "duplicates": r.duplicates}))
    elif a.cmd == "build":
        print(json.dumps({"models": b.build(a.as_of)}))
    elif a.cmd == "check":
        res = b.check(a.as_of)
        failing = [c for c in res if c.status == "fail"]
        print(json.dumps({"checks": len(res), "failing": [f"{c.name} {c.scope}: {c.detail}" for c in failing]}, indent=1))
    elif a.cmd == "invoice":
        acts = b.invoice(a.as_of)
        print(json.dumps([vars(x) for x in acts], indent=1))
    elif a.cmd == "run":
        r = b.run(a.as_of)
        print(json.dumps({"files": r.files, "rows": r.rows, "failing": sum(c.status == "fail" for c in r.checks),
                          "actions": [vars(x) for x in r.actions]}, indent=1))
    elif a.cmd == "schedule":
        b.run_schedule(last=a.until, on_run=lambda r: print(
            f"{r.as_of:%Y-%m-%d %H:%M} files={r.files} rows={r.rows} failing={sum(c.status == 'fail' for c in r.checks)} "
            f"issued={sum(x.action in ('issued', 'adjusted') for x in r.actions)}", flush=True))
    elif a.cmd == "ask":
        from .metrics.ask import answer, reader_for

        reader, catalog = reader_for(b.wh, claude=a.claude)
        print(json.dumps(answer(a.question, reader, catalog, _query(b), a.today), indent=1, default=str))
    return 0


def _query(b):
    def q(sql: str, params: list):
        if "invoice_register" in sql:
            return b.control.query(sql.replace("?", "%s"), params)
        return b.wh.q(sql, params)
    return q


if __name__ == "__main__":
    sys.exit(main())
