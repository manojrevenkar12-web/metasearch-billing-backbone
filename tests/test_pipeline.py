import ast
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mbb.pipeline.landing import LandingView
from mbb.pipeline.run import Backbone
from mbb.pipeline.settings import SAFEGUARDS, Settings

ROOT = Path(__file__).resolve().parent.parent
UTC = timezone.utc


def settings(*off):
    s = Settings.load(ROOT / "config" / "pipeline.toml")
    s = Settings(raw=dict(s.raw, first_run="2026-09-25T06:00Z", last_run="2026-10-08T06:00Z"),
                 safeguards=dict(s.safeguards))
    return s.without(*off) if off else s


@pytest.fixture(scope="module")
def backbone(small_world):
    b = Backbone(small_world, settings())
    b.run_schedule()
    return b


def test_nothing_in_the_pipeline_reads_the_truth():
    for f in (ROOT / "src" / "mbb").rglob("*.py"):
        if "world" in f.parts:
            continue
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            assert not any("world" in n for n in names) or f.name == "cli.py", f
        assert "truth/" not in f.read_text(), f


def test_landing_view_shows_only_what_has_arrived(small_world):
    early = LandingView(small_world / "landing", datetime(2026, 10, 1, 6, tzinfo=UTC))
    late = LandingView(small_world / "landing", datetime(2026, 10, 4, 6, tzinfo=UTC))
    hour = "clicks/cheapflights/2026-09-30T20.jsonl.gz"
    assert not early.has(hour) and late.has(hour)


def test_a_file_is_loaded_once_and_only_when_complete(backbone):
    rows = backbone.control.query("select status, count(*) from file_ledger group by status")
    status = dict(rows)
    assert status["loaded"] > 200
    per_file = backbone.wh.q("""select count(*) from (select path, count(distinct loaded_at) n from raw_clicks
                                group by path) where n > 1""")[0][0]
    assert per_file == 0
    dup = backbone.wh.q("select count(*) from (select click_id from int_clicks_unique group by 1 having count(*) > 1)")
    assert dup[0][0] == 0


def test_month_is_held_while_hours_are_missing_then_issued(backbone):
    docs = backbone.control.register()
    first_issue = {(p, m): at for _, p, m, kind, v, *_rest, at, _o in docs if v == 1}
    held = backbone.control.query(
        "select count(*) from check_result where check_name = 'files_complete' and status = 'fail'")[0][0]
    assert held > 0
    issued = [at for (p, m), at in first_issue.items() if m == "2026-09"]
    assert issued and min(issued) >= datetime(2026, 10, 3, 9, tzinfo=UTC)


def test_late_amendment_becomes_a_note_not_an_overwrite(backbone):
    docs = [d for d in backbone.control.register() if d[1] == "P08" and d[2] == "2026-09"]
    assert docs[0][3] == "invoice"
    assert any(d[3] == "debit_note" for d in docs[1:])


def test_every_check_is_recorded_and_alerts_raised_once(backbone):
    n = backbone.control.query("select count(*) from check_result")[0][0]
    assert n > 100
    dup = backbone.control.query("select count(*) from (select check_name, scope from alert_log group by 1, 2 having count(*) > 1)")
    assert dup[0][0] == 0
    names = {c for (c,) in backbone.control.query("select distinct check_name from alert_log")}
    assert {"duplicate_click_ids", "invalid_traffic_share", "values_in_contract_daily", "fx_published"} <= names


def test_unknown_device_value_is_quarantined_then_released(small_world):
    b = Backbone(small_world, settings())
    b.run_schedule(last=datetime(2026, 10, 2, 6, tzinfo=UTC))
    held = b.wh.q("select count(*) from stg_quarantine")[0][0]
    assert held > 0
    b.run_schedule(first=datetime(2026, 10, 5, 6, tzinfo=UTC), last=datetime(2026, 10, 5, 6, tzinfo=UTC))
    assert b.wh.q("select count(*) from stg_quarantine")[0][0] == 0


def test_partner_months_follow_the_partners_clock(backbone):
    # 2026-09-30 22:30 UTC is already October in Berlin and still September in New York
    rows = dict(backbone.wh.q("""select billing_tz, min(local_date) from fct_billable_clicks f
        join partners p using (partner_id) where f.ts >= timestamp with time zone '2026-09-30 22:00:00+00'
        and f.ts < timestamp with time zone '2026-09-30 23:00:00+00' group by billing_tz"""))
    assert str(rows["Europe/Berlin"]) == "2026-10-01"
    assert str(rows["America/New_York"]) == "2026-09-30"


def test_money_is_integer_minor_units(backbone):
    types = dict(backbone.wh.q("select column_name, data_type from information_schema.columns "
                               "where table_name = 'mart_invoice_lines'"))
    assert types["amount_minor"] in ("BIGINT", "HUGEINT")


@pytest.mark.parametrize("off", SAFEGUARDS)
def test_each_safeguard_can_be_switched_off(small_world, off):
    b = Backbone(small_world, settings(off))
    b.run_schedule(last=datetime(2026, 10, 3, 6, tzinfo=UTC), build_days={3})
    assert b.wh.q("select count(*) from fct_billable_clicks")[0][0] > 0
