"""Certified metrics and the plan -> SQL compiler. A plan names a metric, dimensions, filters and a period;
code checks every part against config/metrics.toml before any SQL is written, and values are always bound
parameters."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass
class Plan:
    metric: str | None
    by: list[str] = field(default_factory=list)
    filters: dict[str, str] = field(default_factory=dict)
    start: date | None = None
    end: date | None = None  # exclusive
    refusal: str | None = None

    def key(self) -> tuple:
        return (self.metric, tuple(sorted(self.by)), tuple(sorted(self.filters.items())), self.start, self.end)


class Catalog:
    def __init__(self, path: str | Path):
        with open(path, "rb") as f:
            self.metrics = tomllib.load(f)["metrics"]

    def validate(self, plan: Plan) -> str | None:
        if plan.refusal:
            return plan.refusal
        if plan.metric not in self.metrics:
            return "no certified metric answers that; the certified ones are " + ", ".join(self.metrics)
        dims = self.metrics[plan.metric]["dimensions"]
        for d in list(plan.by) + list(plan.filters):
            if d not in dims:
                return f"{self.metrics[plan.metric]['label']} cannot be cut by {d}"
        return None

    def compile(self, plan: Plan) -> tuple[str, list]:
        err = self.validate(plan)
        if err:
            raise ValueError(err)
        m = self.metrics[plan.metric]
        dims = m["dimensions"]
        cols = [f"{dims[d]} as {d}" for d in plan.by]
        where, params = [], []
        for d, v in sorted(plan.filters.items()):
            where.append(f"{dims[d]} = ?")
            params.append(v)
        if plan.start:
            where.append(f"{m['time']} >= ?")
            params.append(plan.start)
        if plan.end:
            where.append(f"{m['time']} < ?")
            params.append(plan.end)
        sql = f"select {', '.join(cols + [m['expression'] + ' as value'])} from {m['table']}"
        if where:
            sql += " where " + " and ".join(where)
        if plan.by:
            sql += " group by " + ", ".join(dims[d] for d in plan.by) + " order by " + ", ".join(
                str(i + 1) for i in range(len(plan.by)))
        return sql, params
