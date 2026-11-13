"""Pipeline settings, read from config/pipeline.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

SAFEGUARDS = (
    "complete_files_only", "load_content_once", "dedupe_click_ids", "repeat_click_window", "bot_rules",
    "partner_local_time", "quarantine_unknown_values", "reprice_amendments", "fx_as_published", "hold_invoices",
    "adjustment_notes",
)


@dataclass(frozen=True)
class Settings:
    raw: dict
    safeguards: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path = "config/pipeline.toml") -> "Settings":
        with open(path, "rb") as f:
            raw = tomllib.load(f)
        return cls(raw=raw, safeguards=dict(raw["safeguards"]))

    def on(self, name: str) -> bool:
        return bool(self.safeguards[name])

    def without(self, *names: str) -> "Settings":
        sg = dict(self.safeguards)
        for n in names:
            if n not in sg:
                raise KeyError(n)
            sg[n] = False
        return replace(self, safeguards=sg)

    def naive(self) -> "Settings":
        return self.without(*SAFEGUARDS)

    @property
    def first_run(self) -> datetime:
        return datetime.fromisoformat(self.raw["first_run"].replace("Z", "+00:00"))

    @property
    def last_run(self) -> datetime:
        return datetime.fromisoformat(self.raw["last_run"].replace("Z", "+00:00"))

    def section(self, name: str) -> dict:
        return self.raw[name]
