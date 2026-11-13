"""The analytical store (DuckDB here; the same models run on Trino) and the SQL model runner."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from .landing import LandingView
from .settings import Settings

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
RAW_DDL = """create table if not exists raw_clicks (
    rid bigint, path varchar, click_id varchar, search_id varchar, session_id varchar, offer_id varchar,
    brand varchar, partner_id varchar, market varchar, device varchar, ts timestamp with time zone, ip varchar,
    user_agent varchar, asn_type varchar, search_to_click_ms bigint, loaded_at timestamp with time zone)"""
JSON_COLUMNS = ("{click_id: 'VARCHAR', search_id: 'VARCHAR', session_id: 'VARCHAR', offer_id: 'VARCHAR', "
                "brand: 'VARCHAR', partner_id: 'VARCHAR', market: 'VARCHAR', device: 'VARCHAR', ts: 'VARCHAR', "
                "ip: 'VARCHAR', user_agent: 'VARCHAR', asn_type: 'VARCHAR', search_to_click_ms: 'BIGINT'}")


def model_files() -> list[Path]:
    return sorted(MODELS_DIR.glob("*.sql"))


def model_name(p: Path) -> str:
    return re.sub(r"^\d+_", "", p.stem)


def render(sql: str, params: dict) -> str:
    def sub(m: re.Match) -> str:
        return str(params[m.group(1)])
    return re.sub(r"\$\{(\w+)\}", sub, sql)


def model_params(settings: Settings, as_of: datetime) -> dict:
    br = settings.section("bot_rules")
    markers = " or ".join(f"lower(u.user_agent) like '%{m}%'" for m in br["agent_markers"])
    p = {k: ("true" if v else "false") for k, v in settings.safeguards.items()}
    p |= {"as_of": f"timestamp with time zone '{as_of.astimezone(timezone.utc):%Y-%m-%d %H:%M:%S}+00:00'",
          "agent_marker_predicate": f"({markers})",
          "min_search_to_click_ms": int(br["min_search_to_click_ms"]),
          "max_clicks_per_ip24_hour": int(br["max_clicks_per_ip24_hour"])}
    return p


@dataclass
class LoadResult:
    files: int = 0
    rows: int = 0
    waiting: int = 0
    duplicates: int = 0


class Warehouse:
    def __init__(self, path: str = ":memory:"):
        self.con = duckdb.connect(path)
        self.con.execute("set TimeZone = 'UTC'")
        self.con.execute(RAW_DDL)
        self.next_rid = self.con.execute("select coalesce(max(rid), 0) + 1 from raw_clicks").fetchone()[0]

    # ---------------------------------------------------------------- clicks
    def load_clicks(self, view: LandingView, control, settings: Settings, as_of: datetime) -> LoadResult:
        res = LoadResult()
        ledger = control.ledger()
        hashes = control.loaded_hashes()
        to_load: list[tuple[str, Path, str]] = []
        for path in view.paths("clicks/"):
            if path.endswith(".manifest"):
                continue
            prev = ledger.get(path)
            if prev and prev[2] in ("loaded", "duplicate"):
                continue  # a path is loaded once
            data = view.read_bytes(path)
            sha = hashlib.sha256(data).hexdigest()
            if settings.on("complete_files_only"):
                if not view.has(path + ".manifest"):
                    control.record_file(path, view.object_id(path), sha, 0, "waiting", as_of, "no manifest yet")
                    res.waiting += 1
                    continue
                man = json.loads(view.read_text(path + ".manifest"))
                if man["sha256"] != sha:
                    control.record_file(path, view.object_id(path), sha, 0, "waiting", as_of,
                                        "bytes do not match the manifest")
                    res.waiting += 1
                    continue
            if settings.on("load_content_once") and sha in hashes:
                control.record_file(path, view.object_id(path), sha, 0, "duplicate", as_of, "same bytes already loaded")
                res.duplicates += 1
                continue
            hashes.add(sha)
            if len(gzip.decompress(data)) == 0:
                control.record_file(path, view.object_id(path), sha, 0, "loaded", as_of, "empty hour")
                res.files += 1
                continue
            to_load.append((path, view.object_path(path), sha))
        if to_load:
            files = [str(p) for _, p, _ in to_load]
            before = self.con.execute("select count(*) from raw_clicks").fetchone()[0]
            self.con.execute("create or replace temp table _paths (filename varchar, path varchar)")
            self._insert("_paths", [(str(p), lp) for lp, p, _ in to_load])
            self.con.execute(f"""
                insert into raw_clicks
                select {self.next_rid} - 1 + row_number() over () as rid, p.path, j.click_id, j.search_id,
                       j.session_id, j.offer_id, j.brand, j.partner_id, j.market, j.device,
                       cast(j.ts as timestamp with time zone), j.ip, j.user_agent, j.asn_type,
                       j.search_to_click_ms, ?
                from read_json(?, format = 'newline_delimited', compression = 'gzip', columns = {JSON_COLUMNS}, filename = true) j
                join _paths p on p.filename = j.filename""", [as_of, files])
            after = self.con.execute("select count(*) from raw_clicks").fetchone()[0]
            self.next_rid += after - before
            counts = dict(self.con.execute(
                "select path, count(*) from raw_clicks where loaded_at = ? group by path", [as_of]).fetchall())
            control.record_files([(lp, view.object_id(lp), sha, counts.get(lp, 0), "loaded", as_of, "")
                                  for lp, _, sha in to_load])
            res.files += len(to_load)
            res.rows += after - before
        return res

    # ---------------------------------------------------------------- reference data, rebuilt each run
    def load_reference(self, view: LandingView) -> None:
        key = tuple(p for p in view.latest if not p.startswith("clicks/"))
        if key == getattr(self, "_reference_key", None):
            return  # nothing new from contracts, rates or partners since the last run
        self._reference_key = key
        con = self.con
        rows = list(csv.DictReader(io.StringIO(view.read_text("contracts/partners.csv"))))
        jan = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)
        con.execute("""create or replace table partners (partner_id varchar, name varchar, vertical varchar,
            currency varchar, billing_tz varchar, repeat_window_s integer, std_offset_h integer)""")
        self._insert("partners", [
            (r["partner_id"], r["name"], r["vertical"], r["currency"], r["billing_tz"], int(r["repeat_window_s"]),
             int(jan.astimezone(ZoneInfo(r["billing_tz"])).utcoffset().total_seconds() // 3600)) for r in rows])
        con.execute("""create or replace table rate_card (partner_id varchar, market varchar, device varchar,
            cpc_minor bigint, valid_from date, recorded_at timestamp with time zone)""")
        card = []
        for path in view.paths("contracts/rate_card"):
            for r in csv.DictReader(io.StringIO(view.read_text(path))):
                card.append((r["partner_id"], r["market"], r["device"], int(r["cpc_minor"]), r["valid_from"],
                             view.arrival(path)))
        self._insert("rate_card", card)
        con.execute("create or replace table enum_map (brand varchar, field varchar, value varchar, canonical varchar)")
        latest: dict[str, str] = {}
        for path in view.paths("contracts/schema_"):
            brand, ver = re.match(r"contracts/schema_(\w+?)_v(\d+)\.json", path).groups()
            if brand not in latest or int(ver) > int(re.search(r"_v(\d+)", latest[brand]).group(1)):
                latest[brand] = path
        emap = []
        for brand, path in latest.items():
            schema = json.loads(view.read_text(path))
            aliases = schema.get("aliases", {})
            for fld in ("device", "market"):
                for v in schema[fld]:
                    canon = aliases.get(fld, {}).get(v.lower(), v)
                    emap.append((brand, fld, v.lower(), canon))
                for a, canon in aliases.get(fld, {}).items():
                    emap.append((brand, fld, a.lower(), canon))
        self._insert("enum_map", sorted(set(emap)))
        con.execute("""create or replace table fx_rates (day date, currency varchar, rate double,
            recorded_at timestamp with time zone)""")
        fx = []
        for path in view.paths("fx/"):
            day = path[len("fx/ecb_"):-4]
            for r in csv.DictReader(io.StringIO(view.read_text(path))):
                fx.append((day, r["currency"], float(r["rate"]), view.arrival(path)))
        self._insert("fx_rates", fx)
        con.execute("""create or replace table partner_reports (partner_id varchar, month varchar, clicks bigint,
            recorded_at timestamp with time zone)""")
        rep = []
        for path in view.paths("partner_reports/"):
            for r in csv.DictReader(io.StringIO(view.read_text(path))):
                rep.append((r["partner_id"], r["month"], int(r["clicks"]), view.arrival(path)))
        self._insert("partner_reports", rep)

    # ---------------------------------------------------------------- models
    def build(self, settings: Settings, as_of: datetime) -> int:
        params = model_params(settings, as_of)
        for f in model_files():
            text = f.read_text()
            sql = render(text, params)
            kind = "view" if "-- materialize: view" in text else "table"
            name = model_name(f)
            other = "table" if kind == "view" else "view"
            if self.con.execute(f"select count(*) from duckdb_{other}s() where {other}_name = ? and not internal",
                                [name]).fetchone()[0]:
                self.con.execute(f"drop {other} {name}")
            self.con.execute(f"create or replace {kind} {name} as {sql}")
        return len(model_files())

    def _insert(self, table: str, rows: list[tuple]) -> None:
        if rows:
            cols = [c[0] for c in self.con.execute(f"select * from {table} limit 0").description]
            df = pd.DataFrame(rows, columns=cols)
            self.con.register("_rows", df)
            self.con.execute(f"insert into {table} select * from _rows")
            self.con.unregister("_rows")

    def q(self, sql: str, params: list | tuple = ()) -> list[tuple]:
        return self.con.execute(sql, params).fetchall()
