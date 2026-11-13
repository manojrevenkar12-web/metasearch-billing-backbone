"""The daily billing run on Airflow: load, build, check, invoice. Each task calls the same CLI Rundeck calls.

The run is idempotent for a given as-of time: a file is loaded once, models are rebuilt from the tables,
checks are appended under the run id, and invoicing only ever adds documents.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

STATE = os.environ.get("MBB_STATE", "/data/warehouse.duckdb")
WORLD = os.environ.get("MBB_WORLD", "/data/world")
AS_OF = "{{ data_interval_end.strftime('%Y-%m-%dT%H:%MZ') }}"
COMMON = f"--world {WORLD} --state {STATE} --as-of {AS_OF}"

with DAG(
    dag_id="metasearch_billing_backbone",
    description="Redirect logs to partner invoices, with checks that hold a wrong invoice",
    schedule="0 6 * * *",
    start_date=datetime(2026, 9, 2, 6),
    catchup=False,
    max_active_runs=1,  # runs share one warehouse; a second run waits rather than racing it
    default_args={"retries": 2, "retry_delay": timedelta(minutes=10), "execution_timeout": timedelta(minutes=45)},
    tags=["billing", "bi"],
) as dag:
    load = BashOperator(task_id="load", bash_command=f"mbb load {COMMON}")
    build = BashOperator(task_id="build", bash_command=f"mbb build {COMMON}")
    check = BashOperator(task_id="check", bash_command=f"mbb check {COMMON}")
    invoice = BashOperator(task_id="invoice", bash_command=f"mbb invoice {COMMON}")
    load >> build >> check >> invoice
