"""Score the backbone, a first-version pipeline and each safeguard switched off, against the world's truth.

    python3 scripts/evaluate.py              # dev world -> reports/dev.json
    python3 scripts/evaluate.py --check      # recompute and compare with the committed reports/dev.json
    python3 scripts/evaluate.py --heldout    # the held-out world, once (config/heldout.lock)

This is the only code, with the demo command, that reads truth/.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import duckdb  # noqa: E402

from mbb.pipeline.run import Backbone  # noqa: E402
from mbb.pipeline.settings import SAFEGUARDS, Settings  # noqa: E402
from mbb.world.sim import generate, load_config  # noqa: E402

UTC = timezone.utc
MONTHS = ["2026-09", "2026-10"]
INCIDENT_CHECKS = {
    "outage": ["hourly_files_in", "files_complete"],
    "double_firing": ["duplicate_click_ids"],
    "bot_storm": ["invalid_traffic_share"],
    "enum_drift": ["values_in_contract_daily", "values_in_contract"],
    "fx_delay": ["fx_published"],
}


def variants(settings: Settings) -> dict[str, Settings]:
    out = {"backbone": settings, "first_version": settings.naive()}
    for s in SAFEGUARDS:
        out[f"without_{s}"] = settings.without(s)
    return out


def run_variant(args: tuple[str, str, str]) -> dict:
    world, name, settings_path = args
    settings = variants(Settings.load(settings_path))[name]
    b = Backbone(world, settings, variant=name)
    build_days = None if name == "backbone" else set(
        range(settings.section("invoicing")["issue_from_day"], settings.section("invoicing")["hold_limit_day"] + 2))
    b.run_schedule(build_days=build_days)
    con = b.wh.con
    out = {
        "register": [list(map(_plain, r)) for r in b.control.register()],
        "alerts": [list(map(_plain, r)) for r in b.control.query(
            "select raised_at, check_name, scope, detail from alert_log order by raised_at, check_name, scope")],
        "checks_run": b.control.query("select count(*) from check_result")[0][0],
        "checks_failed": b.control.query("select count(*) from check_result where status = 'fail'")[0][0],
        "revenue": [list(map(_plain, r)) for r in con.execute(
            "select day, sum(revenue_eur_minor) from mart_daily_revenue group by day order by day").fetchall()],
        "flags": [list(map(_plain, r)) for r in con.execute(
            """select click_id, max(case when invalid_reason is null then 0 else 1 end), min(invalid_reason)
               from int_clicks_scored group by click_id""").fetchall()] if name == "backbone" else None,
        "files": dict(con.execute("select status, count(*) from file_ledger group by status").fetchall()),
    }
    return out


def _plain(v):
    if isinstance(v, datetime):
        return v.astimezone(UTC).isoformat()
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


# ---------------------------------------------------------------------------------------------- truth
class Truth:
    def __init__(self, world: Path):
        t = world / "truth"
        self.con = duckdb.connect()
        self.con.execute("set TimeZone = 'UTC'")
        self.con.execute(f"create table events as select * from read_csv('{t / 'events.csv.gz'}', header = true)")
        self.invoices = {(r["partner_id"], r["month"]): r for r in self.con.execute(
            f"select * from read_csv('{t / 'invoices.csv'}', header = true)").df().to_dict("records")}
        self.fx = json.loads((t / "fx.json").read_text())
        # The best any pipeline can bill from these logs: the truth, plus the bots that are indistinguishable from
        # people in them (residential proxies, real browsers, human pace). Errors against this are avoidable.
        self.reference = {(p, m): (int(n), int(a)) for p, m, n, a in self.con.execute(
            """select partner_id, bill_month, count(*), sum(list_price_minor) from events
               where billable = 1 or (kind = 'bot' and stealth = 1) group by 1, 2""").fetchall()}
        self.meta = json.loads((t / "meta.json").read_text())

    def rate(self, currency: str, day: str) -> float:
        if currency == "EUR":
            return 1.0
        best = max(d for d in self.fx if d <= day)
        return self.fx[best][currency]

    def revenue(self) -> dict[str, int]:
        rows = self.con.execute("""select cast(ts as date) as d, partner_id, sum(price_minor)
                                   from events where billable = 1 group by 1, 2""").fetchall()
        cur = {pid: c for (pid, _), r in self.invoices.items() for c in [r["currency"]]}
        out: dict[str, int] = {}
        for d, pid, amt in rows:
            ds = d.isoformat()
            out[ds] = out.get(ds, 0) + int(round(amt / self.rate(cur[pid], ds)))
        return out


# ---------------------------------------------------------------------------------------------- scoring
def score_invoices(v: dict, truth: Truth) -> dict:
    docs: dict[tuple, list] = {}
    for _doc, pid, mo, kind, _ver, _cur, clicks, amt, at, open_checks in v["register"]:
        docs.setdefault((pid, mo), []).append((kind, int(amt), int(clicks), at, open_checks))
    rows, eur = [], lambda amt, cur: amt / truth.rate(cur, "2026-10-30")
    for (pid, mo), t in sorted(truth.invoices.items()):
        if mo not in MONTHS:
            continue
        d = docs.get((pid, mo), [])
        first = d[0] if d else None
        final = sum(x[1] for x in d)
        ref = truth.reference[(pid, mo)][1]
        rows.append({
            "partner": pid, "month": mo, "currency": t["currency"], "true_minor": int(t["amount_minor"]),
            "true_clicks": int(t["clicks"]), "first_minor": first[1] if first else None,
            "first_clicks": first[2] if first else None,
            "final_minor": final, "issued": first[3] if first else None, "notes": len(d) - 1 if d else 0,
            "first_err_eur": round(eur((first[1] if first else 0) - int(t["amount_minor"]), t["currency"]) / 100, 2),
            "final_err_eur": round(eur(final - int(t["amount_minor"]), t["currency"]) / 100, 2),
            "true_eur": round(eur(int(t["amount_minor"]), t["currency"]) / 100, 2),
            "issued_over_open_checks": bool(first and first[4]),
            "ref_eur": round(eur(ref, t["currency"]) / 100, 2),
            "first_avoidable_err_eur": round(eur((first[1] if first else 0) - ref, t["currency"]) / 100, 2),
            "final_avoidable_err_eur": round(eur(final - ref, t["currency"]) / 100, 2),
        })
    total = sum(r["true_eur"] for r in rows)
    first_abs = sum(abs(r["first_err_eur"]) for r in rows)
    final_abs = sum(abs(r["final_err_eur"]) for r in rows)
    tol = 0.005
    ref_total = sum(r["ref_eur"] for r in rows)
    fa = sum(abs(r["first_avoidable_err_eur"]) for r in rows)
    la = sum(abs(r["final_avoidable_err_eur"]) for r in rows)
    return {
        "first_issue_avoidable_error_eur": round(fa, 2),
        "final_avoidable_error_eur": round(la, 2),
        "first_issue_avoidable_error_pct": round(100 * fa / ref_total, 3),
        "final_avoidable_error_pct": round(100 * la / ref_total, 3),
        "invoices_avoidably_wrong_first_issue": sum(1 for r in rows if abs(r["first_avoidable_err_eur"]) > tol * r["ref_eur"]),
        "invoices_avoidably_wrong_final": sum(1 for r in rows if abs(r["final_avoidable_err_eur"]) > tol * r["ref_eur"]),
        "indistinguishable_bot_billing_eur": round(ref_total - total, 2),
        "invoices": len(rows),
        "true_billing_eur": round(total, 2),
        "first_issue_abs_error_eur": round(first_abs, 2),
        "final_abs_error_eur": round(final_abs, 2),
        "first_issue_error_pct": round(100 * first_abs / total, 3),
        "final_error_pct": round(100 * final_abs / total, 3),
        "net_final_error_eur": round(sum(r["final_err_eur"] for r in rows), 2),
        "invoices_wrong_first_issue": sum(1 for r in rows if abs(r["first_err_eur"]) > tol * r["true_eur"]),
        "invoices_wrong_final": sum(1 for r in rows if abs(r["final_err_eur"]) > tol * r["true_eur"]),
        "adjustment_notes": sum(r["notes"] for r in rows),
        "latest_issue_day": max((int(r["issued"][8:10]) for r in rows if r["issued"]), default=None),
        "issued_with_open_checks": sum(1 for r in rows if r["issued_over_open_checks"]),
        "rows": rows,
    }


def score_disputes(inv: dict, truth: Truth, world: Path, tolerance: float) -> int:
    rep = {}
    for p in (world / "landing" / "objects").glob("*/partner_reports/*.csv"):
        lines = p.read_text().splitlines()[1:]
        for line in lines:
            pid, mo, clicks = line.split(",")
            rep[(pid, mo)] = int(clicks)
    n = 0
    for r in inv["rows"]:
        k = (r["partner"], r["month"])
        if k in rep and r["first_clicks"] is not None and abs(r["first_clicks"] - rep[k]) / rep[k] > tolerance:
            n += 1
    return n


def score_detection(v: dict, truth: Truth) -> list[dict]:
    out = []
    for inc in truth.meta["incidents"]:
        kind = inc["kind"]
        if kind not in INCIDENT_CHECKS:
            continue
        if kind == "fx_delay":
            start = datetime.fromisoformat(inc["first"]).replace(hour=15, tzinfo=UTC)
            scope_hint = "ecb/"
        else:
            start = datetime.fromisoformat(inc["start"].replace("Z", "+00:00"))
            scope_hint = inc["brand"] + "/"
        last_day = datetime.fromisoformat(inc.get("end", inc.get("last", "") + "T00:00Z" if kind == "fx_delay" else
                                                   inc["start"]).replace("Z", "+00:00"))

        def matches(a, kind=kind, start=start, last_day=last_day, scope_hint=scope_hint) -> bool:
            if a[1] not in INCIDENT_CHECKS[kind] or datetime.fromisoformat(a[0]) < start - timedelta(hours=1):
                return False
            if a[1] in ("files_complete", "values_in_contract"):  # partner/month scopes: the month must contain it
                return a[2].split("/")[1] == start.strftime("%Y-%m")
            if not a[2].startswith(scope_hint):
                return False
            if kind == "fx_delay":
                return True
            day = a[2].split("/")[1]  # brand/day scopes: the day judged must be one the incident touched
            return start.date().isoformat() <= day <= max(start, last_day - timedelta(seconds=1)).date().isoformat()

        hits = [a for a in v["alerts"] if matches(a)]
        first = min(hits, key=lambda a: a[0]) if hits else None
        out.append({
            "incident": kind, "where": inc.get("brand", "ECB reference rates"), "start": start.isoformat(),
            "caught": bool(first), "first_check": first[1] if first else None,
            "hours_to_alert": round((datetime.fromisoformat(first[0]) - start).total_seconds() / 3600, 1) if first else None,
        })
    return out


def score_bot_filter(v: dict, truth: Truth) -> dict:
    con = truth.con
    import pandas as pd

    con.register("flags_df", pd.DataFrame(v["flags"], columns=["click_id", "flagged", "reason"]))
    con.execute("create or replace table flags as select * from flags_df")
    r = con.execute("""
        select count(*) filter (where e.kind <> 'human' and f.flagged = 1),
               count(*) filter (where f.flagged = 1),
               count(*) filter (where e.kind <> 'human'),
               count(*) filter (where e.kind = 'bot' and e.stealth = 0),
               count(*) filter (where e.kind = 'bot' and e.stealth = 0 and f.flagged = 1),
               count(*) filter (where e.kind = 'human' and f.flagged = 1),
               count(*) filter (where e.kind = 'human'),
               count(*) filter (where e.storm = 1), count(*) filter (where e.storm = 1 and f.flagged = 1)
        from events e join flags f using (click_id)""").fetchone()
    tp, flagged, invalid, crude, crude_hit, fp, humans, storm, storm_hit = r
    return {
        "precision": round(tp / flagged, 4), "recall_all_invalid": round(tp / invalid, 4),
        "recall_detectable_bots": round(crude_hit / crude, 4), "people_flagged": fp,
        "people_flagged_share": round(fp / humans, 5), "storm_recall": round(storm_hit / storm, 4) if storm else None,
        "undetectable_bot_clicks": invalid - tp - (crude - crude_hit),
    }


def score_revenue(v: dict, truth: Truth) -> dict:
    t = truth.revenue()
    got = {d: (int(x) if x is not None else 0) for d, x in v["revenue"]}
    days = sorted(t)
    abs_err = sum(abs(got.get(d, 0) - t[d]) for d in days)
    total = sum(t.values())
    return {"days": len(days), "abs_error_eur": round(abs_err / 100, 2), "error_pct": round(100 * abs_err / total, 3),
            "worst_day_error_pct": round(max(100 * abs(got.get(d, 0) - t[d]) / t[d] for d in days), 2)}


def evaluate(world_cfg: Path, settings_path: Path, workers: int, only: list[str] | None = None,
             reuse: bool = False) -> dict:
    cfg = load_config(world_cfg)
    world = ROOT / "data" / cfg["name"]
    cache = world.parent / f"{cfg['name']}-runs.json"
    settings = Settings.load(settings_path)
    names = [n for n in variants(settings) if not only or n in only]
    if reuse and cache.exists():  # rescoring only: the runs are what the code produced last time
        results = {n: r for n, r in json.loads(cache.read_text()).items() if n in names}
    else:
        generate(world_cfg, world)
        with ProcessPoolExecutor(max_workers=workers) as ex:
            results = dict(zip(names, ex.map(run_variant, [(str(world), n, str(settings_path)) for n in names])))
        cache.write_text(json.dumps(results))
    truth = Truth(world)
    tol = settings.section("checks")["partner_report_tolerance"]
    report = {"world": cfg["name"], "seed": cfg["seed"], "variants": {}}
    for n, v in results.items():
        inv = score_invoices(v, truth)
        entry = {k: x for k, x in inv.items() if k != "rows"}
        entry["partner_disputes"] = score_disputes(inv, truth, world, tol)
        entry["revenue"] = score_revenue(v, truth)
        entry["files"] = v["files"]
        if n in ("backbone", "first_version"):
            entry["invoice_rows"] = inv["rows"]
            entry["alerts"] = len(v["alerts"])
            entry["checks_run"] = v["checks_run"]
            entry["checks_failed"] = v["checks_failed"]
        if n == "backbone":
            entry["detection"] = score_detection(v, truth)
            entry["bot_filter"] = score_bot_filter(v, truth)
            entry["alert_log"] = v["alerts"]
            entry["register"] = v["register"]
        report["variants"][n] = entry
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--heldout", action="store_true")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--only", nargs="*", help="debug: score only these variants, write nothing")
    ap.add_argument("--reuse", action="store_true", help="rescore the last runs without running them again")
    a = ap.parse_args()
    settings = ROOT / "config" / "pipeline.toml"
    if a.heldout:
        lock = ROOT / "config" / "heldout.lock"
        if a.reuse and lock.exists():  # rescoring the one held-out run; the pipeline is not run again
            rep = evaluate(ROOT / "config" / "world_heldout.toml", settings, a.workers, reuse=True)
            (ROOT / "reports" / "heldout.json").write_text(json.dumps(rep, indent=1, sort_keys=True) + "\n")
            print("rescored reports/heldout.json from the recorded run")
            return
        if lock.exists():
            sys.exit(f"the held-out world has been run ({lock.read_text().strip()}); measure changes on dev")
        rep = evaluate(ROOT / "config" / "world_heldout.toml", settings, a.workers)
        out = ROOT / "reports" / "heldout.json"
        out.write_text(json.dumps(rep, indent=1, sort_keys=True) + "\n")
        lock.write_text(f"run once on {datetime.now(UTC):%Y-%m-%d}\n")
        print(f"wrote {out}")
        return
    if a.only:
        rep = evaluate(ROOT / "config" / "world.toml", settings, a.workers, a.only)
        for n, v in rep["variants"].items():
            print(n, json.dumps({k: x for k, x in v.items() if k not in ("invoice_rows", "alert_log", "register")}, indent=1))
        return
    rep = evaluate(ROOT / "config" / "world.toml", settings, a.workers, reuse=a.reuse and not a.check)
    out = ROOT / "reports" / "dev.json"
    text = json.dumps(rep, indent=1, sort_keys=True) + "\n"
    if a.check:
        if out.read_text() != text:
            sys.exit("reports/dev.json is not what the code produces: run scripts/evaluate.py")
        print("reports/dev.json matches")
        return
    out.write_text(text)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
