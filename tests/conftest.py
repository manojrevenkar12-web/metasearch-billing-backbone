import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from mbb.world.sim import World, load_config  # noqa: E402


@pytest.fixture(scope="session")
def small_world(tmp_path_factory):
    """Two weeks around a month end, small volume, every kind of incident."""
    cfg = load_config(ROOT / "config" / "world.toml")
    cfg = dict(cfg, name="test", start="2026-09-24", days=12, clicks_per_day=900, seed=11)
    cfg["incidents"] = [
        {"kind": "outage", "brand": "cheapflights", "start": "2026-09-30T18:00Z", "end": "2026-10-01T00:00Z",
         "arrives": "2026-10-03T09:00Z"},
        {"kind": "double_firing", "brand": "kayak", "device": "mobile", "start": "2026-09-26T00:00Z",
         "end": "2026-09-27T00:00Z"},
        {"kind": "bot_storm", "brand": "hotelscombined", "market": "DE", "start": "2026-09-28T00:00Z",
         "end": "2026-09-29T00:00Z", "per_day": 400},
        {"kind": "enum_drift", "brand": "momondo", "field": "device", "old": "mobile", "new": "MOBILE_APP",
         "start": "2026-09-29T00:00Z", "contract_arrives": "2026-10-04T11:00Z"},
        {"kind": "amendment", "partner": "P11", "markets": ["DE"], "devices": ["desktop", "mobile"],
         "change": -0.15, "effective": "2026-09-25", "recorded": "2026-09-29T10:00Z"},
        {"kind": "amendment", "partner": "P08", "markets": ["US"], "devices": ["desktop"], "change": 0.10,
         "effective": "2026-09-26", "recorded": "2026-10-05T15:00Z"},
        {"kind": "fx_delay", "first": "2026-09-28", "last": "2026-09-29", "arrives": "2026-10-01T15:00Z"},
    ]
    root = tmp_path_factory.mktemp("world") / "test"
    w = World(cfg, root)
    w.generate()
    return root
