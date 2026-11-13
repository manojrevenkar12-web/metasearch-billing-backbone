"""The control store on PostgreSQL: the same SQL, the same behaviour. Runs when MBB_TEST_PG is set (CI)."""

import os
import uuid
from datetime import datetime, timezone

import pytest

from mbb.pipeline.checks import CheckResult
from mbb.pipeline.control import ControlStore

DSN = os.environ.get("MBB_TEST_PG")
pytestmark = pytest.mark.skipif(not DSN, reason="set MBB_TEST_PG to a PostgreSQL DSN")
AT = datetime(2026, 10, 2, 6, tzinfo=timezone.utc)


@pytest.fixture
def store():
    return ControlStore.postgres(DSN, schema=f"t_{uuid.uuid4().hex[:8]}")


def test_ledger_upserts_by_path(store):
    store.record_file("clicks/kayak/2026-09-30T20.jsonl.gz", "v1/x", "aa", 0, "waiting", AT, "no manifest yet")
    store.record_files([("clicks/kayak/2026-09-30T20.jsonl.gz", "v2/x", "bb", 120, "loaded", AT, "")])
    assert store.ledger()["clicks/kayak/2026-09-30T20.jsonl.gz"] == ("v2/x", "bb", "loaded")
    assert store.loaded_hashes() == {"bb"}


def test_alerts_are_raised_once(store):
    r = CheckResult("duplicate_click_ids", "kayak/2026-10-06", "fail", 0.4, 0.005, False, "x")
    store.record_checks("run-1", AT, [r])
    store.record_checks("run-2", AT, [r])
    assert store.query("select count(*) from alert_log")[0][0] == 1
    assert store.query("select count(*) from check_result")[0][0] == 2


def test_invoice_documents_are_only_added(store):
    store.issue("P01-2026-09-1", "P01", "2026-09", "invoice", 1, "EUR", 100, 6200, AT, "", "lines")
    store.issue("P01-2026-09-2", "P01", "2026-09", "credit_note", 2, "EUR", -3, -186, AT, "", "lines")
    docs = store.documents("P01", "2026-09")
    assert [d[1] for d in docs] == ["invoice", "credit_note"] and sum(d[4] for d in docs) == 6014
    import psycopg

    with pytest.raises(psycopg.errors.UniqueViolation):
        store.issue("P01-2026-09-1", "P01", "2026-09", "invoice", 1, "EUR", 1, 1, AT, "", "lines")
