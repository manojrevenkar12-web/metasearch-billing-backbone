"""The same SQL models in Trino's dialect, translated with sqlglot. CI runs them on a real Trino and compares
every model's rows with DuckDB's."""

from __future__ import annotations

from datetime import datetime, timezone

import sqlglot

from .pipeline.settings import Settings
from .pipeline.warehouse import model_files, model_name, model_params, render


def transpile_models(settings: Settings | None = None, as_of: datetime | None = None) -> list[tuple[str, str]]:
    settings = settings or Settings.load()
    as_of = as_of or datetime(2026, 11, 10, 6, tzinfo=timezone.utc)
    params = model_params(settings, as_of)
    params["as_of"] = "mbb_as_of_marker"
    literal = f"FROM_ISO8601_TIMESTAMP('{as_of.astimezone(timezone.utc):%Y-%m-%dT%H:%M:%S}Z')"
    out = []
    for f in model_files():
        sql = render(f.read_text(), params)
        trino = sqlglot.transpile(sql, read="duckdb", write="trino")[0]
        out.append((model_name(f), trino.replace("mbb_as_of_marker", literal)))
    return out
