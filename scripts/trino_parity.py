"""Run every model on Trino and on DuckDB over the same small world, and compare the rows.

    python3 scripts/trino_parity.py --host localhost --port 8080     (CI starts trinodb/trino as a service)

The models are written once, in DuckDB's dialect, and translated with sqlglot (mbb.trino). This is the test
that the translation, and the SQL itself, mean the same thing on both engines.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from mbb.pipeline.run import Backbone  # noqa: E402
from mbb.pipeline.settings import Settings  # noqa: E402
from mbb.trino import transpile_models  # noqa: E402
from mbb.world.sim import World, load_config  # noqa: E402

UTC = timezone.utc
AS_OF = datetime(2026, 10, 3, 6, tzinfo=UTC)
BASE = {
    "raw_clicks": ["rid bigint", "path varchar", "click_id varchar", "search_id varchar", "session_id varchar",
                   "offer_id varchar", "brand varchar", "partner_id varchar", "market varchar", "device varchar",
                   "ts timestamp(3) with time zone", "ip varchar", "user_agent varchar", "asn_type varchar",
                   "search_to_click_ms bigint", "loaded_at timestamp(3) with time zone"],
    "partners": ["partner_id varchar", "name varchar", "vertical varchar", "currency varchar", "billing_tz varchar",
                 "repeat_window_s integer", "std_offset_h integer"],
    "rate_card": ["partner_id varchar", "market varchar", "device varchar", "cpc_minor bigint", "valid_from date",
                  "recorded_at timestamp(3) with time zone"],
    "enum_map": ["brand varchar", "field varchar", "value varchar", "canonical varchar"],
    "fx_rates": ["day date", "currency varchar", "rate double", "recorded_at timestamp(3) with time zone"],
}


def lit(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, Decimal)):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, datetime):
        return f"TIMESTAMP '{v.astimezone(UTC):%Y-%m-%d %H:%M:%S}.{v.microsecond // 1000:03d} UTC'"
    if isinstance(v, date):
        return f"DATE '{v.isoformat()}'"
    return "'" + str(v).replace("'", "''") + "'"


def norm(v):
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return v.replace(microsecond=v.microsecond // 1000 * 1000).isoformat()
        return v.astimezone(UTC).replace(microsecond=v.microsecond // 1000 * 1000).isoformat()
    if isinstance(v, (float, Decimal)):
        return round(float(v), 6)
    if isinstance(v, date):
        return v.isoformat()
    return v


def small_world(root: Path) -> Path:
    cfg = load_config(ROOT / "config" / "world.toml")
    cfg = dict(cfg, name="parity", start="2026-09-28", days=4, clicks_per_day=500, seed=5)
    cfg["incidents"] = [i for i in cfg["incidents"] if i["kind"] in ("double_firing", "amendment")]
    cfg["incidents"] = [dict(i, start="2026-09-29T00:00Z", end="2026-09-30T00:00Z") if i["kind"] == "double_firing"
                        else dict(i, effective="2026-09-29", recorded="2026-10-01T10:00Z") for i in cfg["incidents"]]
    World(cfg, root).generate()
    return root


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=8080)
    a = ap.parse_args()
    import trino

    with tempfile.TemporaryDirectory() as d:
        world = small_world(Path(d) / "parity")
        settings = Settings.load(ROOT / "config" / "pipeline.toml")
        b = Backbone(world, settings)
        b.run_schedule(first=datetime(2026, 9, 29, 6, tzinfo=UTC), last=AS_OF)
        duck = b.wh.con

        conn = trino.dbapi.connect(host=a.host, port=a.port, user="ci", catalog="memory", schema="default",
                                   session_properties={"query_max_run_time": "10m"}, timezone="UTC")
        cur = conn.cursor()
        for _ in range(60):
            try:
                cur.execute("select 1")
                cur.fetchall()
                break
            except Exception:  # noqa: BLE001 - Trino is still starting
                time.sleep(5)
        for table, cols in BASE.items():
            cur.execute(f"drop table if exists {table}")
            cur.fetchall()
            cur.execute(f"create table {table} ({', '.join(cols)})")
            cur.fetchall()
            names = [c.split()[0] for c in cols]
            rows = duck.execute(f"select {', '.join(names)} from {table}").fetchall()
            for i in range(0, len(rows), 400):
                values = ", ".join("(" + ", ".join(lit(v) for v in r) + ")" for r in rows[i:i + 400])
                cur.execute(f"insert into {table} values {values}")
                cur.fetchall()
            print(f"loaded {table}: {len(rows)} rows")

        failures = 0
        for name, sql in transpile_models(settings, AS_OF):
            cur.execute(f"drop table if exists {name}")
            cur.fetchall()
            cur.execute(f"create table {name} as {sql}")
            cur.fetchall()
            cur.execute(f"select * from {name}")
            t_rows = sorted(tuple(norm(v) for v in r) for r in cur.fetchall())
            d_rows = sorted(tuple(norm(v) for v in r) for r in duck.execute(f"select * from {name}").fetchall())
            same = t_rows == d_rows
            failures += not same
            print(f"{'same' if same else 'DIFFERENT':9} {name}: duckdb {len(d_rows)} rows, trino {len(t_rows)} rows")
            if not same:
                print("  only duckdb:", [r for r in d_rows if r not in set(t_rows)][:3])
                print("  only trino: ", [r for r in t_rows if r not in set(d_rows)][:3])
        if failures:
            sys.exit(f"{failures} models differ between Trino and DuckDB")
        print("every model returns the same rows on Trino and DuckDB")


if __name__ == "__main__":
    main()
