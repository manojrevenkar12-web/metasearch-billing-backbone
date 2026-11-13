import re
from pathlib import Path

import yaml

from mbb.cli import main
from mbb.trino import transpile_models

ROOT = Path(__file__).resolve().parent.parent
STEPS = ["load", "build", "check", "invoice"]


def test_rundeck_runs_the_four_steps_in_order():
    jobs = yaml.safe_load((ROOT / "orchestration" / "rundeck" / "billing-backbone.yaml").read_text())
    cmds = [c["exec"] for c in jobs[0]["sequence"]["commands"]]
    assert [c.split()[1] for c in cmds] == STEPS
    assert jobs[0]["multipleExecutions"] is False


def test_airflow_dag_runs_the_same_steps():
    text = (ROOT / "orchestration" / "airflow" / "dags" / "billing_backbone.py").read_text()
    assert re.findall(r'bash_command=f"mbb (\w+)', text) == STEPS
    assert "load >> build >> check >> invoice" in text and "max_active_runs=1" in text


def test_cli_knows_every_step(capsys):
    for step in STEPS:
        try:
            main([step, "--help"])
        except SystemExit as e:
            assert e.code == 0


def test_every_model_translates_to_trino():
    out = dict(transpile_models())
    assert len(out) == 11
    assert "FROM_ISO8601_TIMESTAMP" in out["int_rate_versions"]
    assert "AT_TIMEZONE" in out["int_clicks_local"]
