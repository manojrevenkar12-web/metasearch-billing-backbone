"""One scheduled run: load what has arrived, rebuild the models, check, invoice, record."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .checks import CheckResult, blocking_checks, monitoring_checks
from .control import ControlStore
from .invoicing import InvoiceAction, run_invoicing
from .landing import LandingView
from .settings import Settings
from .warehouse import Warehouse


@dataclass
class RunResult:
    as_of: datetime
    files: int
    rows: int
    waiting: int
    duplicates: int
    built: bool
    checks: list[CheckResult] = field(default_factory=list)
    actions: list[InvoiceAction] = field(default_factory=list)


class Backbone:
    def __init__(self, world_root: str | Path, settings: Settings, variant: str = "backbone",
                 warehouse: Warehouse | None = None, control: ControlStore | None = None):
        self.landing = Path(world_root) / settings.raw["landing"]
        self.settings = settings
        self.variant = variant
        self.wh = warehouse or Warehouse()
        self.control = control or ControlStore.duckdb(self.wh.con)

    # The four steps a scheduler runs in order. Each one can run on its own against persistent state.
    def load(self, as_of: datetime):
        view = LandingView(self.landing, as_of)
        self.wh.load_reference(view)
        return self.wh.load_clicks(view, self.control, self.settings, as_of)

    def build(self, as_of: datetime) -> int:
        self.wh.load_reference(LandingView(self.landing, as_of))
        return self.wh.build(self.settings, as_of)

    def check(self, as_of: datetime) -> list[CheckResult]:
        results = blocking_checks(self.wh, self.control, self.settings, as_of) + \
            monitoring_checks(self.wh, self.control, self.settings, as_of)
        self.control.record_checks(self._run_id(as_of), as_of, results)
        return results

    def invoice(self, as_of: datetime) -> list[InvoiceAction]:
        recorded = self.control.query(
            "select check_name, scope, status, value, threshold, blocking, detail from check_result where run_id = %s",
            (self._run_id(as_of),))
        checks = [CheckResult(n, s, st, v, th, bool(b), d) for n, s, st, v, th, b, d in recorded]
        return run_invoicing(self.wh, self.control, self.settings, as_of, checks)

    def _run_id(self, as_of: datetime) -> str:
        return f"{self.variant}-{as_of:%Y%m%dT%H%M}"

    def run(self, as_of: datetime, build: bool = True) -> RunResult:
        load = self.load(as_of)
        res = RunResult(as_of, load.files, load.rows, load.waiting, load.duplicates, build)
        models = 0
        if build:
            models = self.build(as_of)
            res.checks = self.check(as_of)
            res.actions = self.invoice(as_of)
        self.control.record_run(self._run_id(as_of), self.variant, as_of, load.files, load.rows, models,
                                sum(1 for c in res.checks if c.blocking and c.status == "fail"),
                                sum(1 for a in res.actions if a.action in ("issued", "adjusted")))
        return res

    def run_schedule(self, first: datetime | None = None, last: datetime | None = None,
                     build_days: set[int] | None = None, on_run=None) -> list[RunResult]:
        t = first or self.settings.first_run
        last = last or self.settings.last_run
        out = []
        while t <= last:
            build = build_days is None or t.day in build_days or t == last
            r = self.run(t, build=build)
            out.append(r)
            if on_run:
                on_run(r)
            t += timedelta(days=1)
        return out
