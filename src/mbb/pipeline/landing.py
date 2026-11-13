"""The landing zone as the pipeline sees it at a moment: every object that has arrived by then.

Brands, the contracts team, the reference-rate feed and partners drop files here. A path can be written more
than once (a half-finished upload, then the whole file), so a view returns the latest object for each path.
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=8)
def _arrivals(root: str) -> tuple[tuple[str, str, datetime], ...]:
    out = []
    with open(Path(root) / "arrivals.jsonl") as f:
        for line in f:
            a = json.loads(line)
            out.append((a["path"], a["object"], datetime.fromisoformat(a["arrival"])))
    return tuple(out)


class LandingView:
    def __init__(self, root: str | Path, as_of: datetime):
        self.root = Path(root)
        self.as_of = as_of
        self.latest: dict[str, tuple[str, datetime]] = {}
        for path, obj, arrival in _arrivals(str(self.root)):
            if arrival <= as_of:
                self.latest[path] = (obj, arrival)

    def paths(self, prefix: str) -> list[str]:
        return sorted(p for p in self.latest if p.startswith(prefix))

    def has(self, path: str) -> bool:
        return path in self.latest

    def object_path(self, path: str) -> Path:
        return self.root / self.latest[path][0]

    def object_id(self, path: str) -> str:
        return self.latest[path][0]

    def arrival(self, path: str) -> datetime:
        return self.latest[path][1]

    def read_bytes(self, path: str) -> bytes:
        return self.object_path(path).read_bytes()

    def read_text(self, path: str) -> str:
        return self.read_bytes(path).decode()
