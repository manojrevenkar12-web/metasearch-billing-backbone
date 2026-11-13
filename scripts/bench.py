"""Two query rewrites in the billing models, timed on the dev world's two months of clicks.

    python3 scripts/bench.py      # -> reports/bench.json

Each pair must return identical rows; the timings are from the machine that ran it and are not checked in CI.
"""

from __future__ import annotations

import json
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from mbb.pipeline.run import Backbone  # noqa: E402
from mbb.pipeline.settings import Settings  # noqa: E402
from mbb.pipeline.warehouse import model_params  # noqa: E402

AS_OF = datetime(2026, 11, 10, 6, tzinfo=timezone.utc)

PAIRS = {
    "price each click by the contract as known now": (
        # every candidate rate per click, then keep the latest: rows multiply by the rate history
        """select b.rid, c.cpc_minor from int_clicks_billable b left join (
             select b2.rid, r.cpc_minor,
                    row_number() over (partition by b2.rid order by r.valid_from desc, r.recorded_at desc) as rk
             from int_clicks_billable b2 join rate_card r
               on r.partner_id = b2.partner_id and r.market = b2.market and r.device = b2.device
              and r.valid_from <= b2.local_date and r.recorded_at <= ${as_of}) c
           on c.rid = b.rid and c.rk = 1""",
        # the contract turned into date intervals once, then one range join
        """select b.rid, v.cpc_minor from int_clicks_billable b left join int_rate_versions v
             on v.partner_id = b.partner_id and v.market = b.market and v.device = b.device
            and b.local_date >= v.valid_from and b.local_date < v.valid_to""",
    ),
    "find repeat clicks inside the partner's window": (
        # a self-join: every click looks for any earlier click on the same offer by the same session inside the
        # window (the same answer: if any earlier click is inside it, the latest one is too)
        """select l.rid, exists (
               select 1 from int_clicks_local s2
               where s2.partner_id = l.partner_id and s2.session_id = l.session_id and s2.offer_id = l.offer_id
                 and (s2.ts < l.ts or (s2.ts = l.ts and s2.rid < l.rid))
                 and date_diff('millisecond', s2.ts, l.ts) < l.repeat_window_s * 1000) as repeat
           from int_clicks_local l""",
        # one window function over the sorted clicks
        """select l.rid, (l.prev_click_ts is not null
                          and date_diff('millisecond', l.prev_click_ts, l.ts) < l.repeat_window_s * 1000) as repeat
           from int_clicks_local l""",
    ),
}


def timed(con, sql: str, n: int = 3) -> tuple[float, list]:
    times, rows = [], None
    for _ in range(n):
        t = time.perf_counter()
        rows = con.execute(f"select * from ({sql}) order by 1").fetchall()
        times.append(time.perf_counter() - t)
    return statistics.median(times), rows


def main() -> None:
    settings = Settings.load(ROOT / "config" / "pipeline.toml")
    b = Backbone(ROOT / "data" / "dev", settings, variant="bench")
    b.run_schedule(last=AS_OF, build_days=set())
    con = b.wh.con
    # materialize the inputs once, so each pair times only its own query
    for name in ("int_clicks_local", "int_clicks_billable", "int_rate_versions"):
        con.execute(f"create or replace temp table bench_{name} as select * from {name}")
    params = model_params(settings, AS_OF)
    clicks = con.execute("select count(*) from int_clicks_billable").fetchone()[0]
    out = {"clicks": clicks, "machine": f"{platform.machine()}, {platform.python_version()}", "pairs": []}
    for name, (slow, fast) in PAIRS.items():
        slow, fast = (s.replace("${as_of}", params["as_of"]) for s in (slow, fast))
        for model in ("int_clicks_billable", "int_clicks_local", "int_rate_versions"):
            slow, fast = slow.replace(model, f"bench_{model}"), fast.replace(model, f"bench_{model}")
        ts, rs = timed(con, slow)
        tf, rf = timed(con, fast)
        out["pairs"].append({"query": name, "before_s": round(ts, 3), "after_s": round(tf, 3),
                             "speedup": round(ts / tf, 1), "identical": rs == rf, "rows": len(rf)})
        print(out["pairs"][-1])
    (ROOT / "reports" / "bench.json").write_text(json.dumps(out, indent=1) + "\n")


if __name__ == "__main__":
    main()
