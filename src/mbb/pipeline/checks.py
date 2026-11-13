"""Checks. Every result is written to the control store; the blocking ones hold an invoice.

Blocking checks are scoped to a partner and a billing month. Monitoring checks are scoped to a brand and a UTC
day and raise an alert the first time they fail.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .settings import Settings

UTC = timezone.utc
HOUR_RE = re.compile(r"clicks/(\w+)/(\d{4}-\d{2}-\d{2}T\d{2})(?:\.r\d+)?\.jsonl\.gz$")


@dataclass(frozen=True)
class CheckResult:
    name: str
    scope: str
    status: str  # "pass" or "fail"
    value: float | None
    threshold: float | None
    blocking: bool
    detail: str = ""


def month_window_utc(month: str, tz: str) -> tuple[datetime, datetime]:
    y, m = map(int, month.split("-"))
    z = ZoneInfo(tz)
    start = datetime(y, m, 1, tzinfo=z)
    end = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=z)
    return start.astimezone(UTC), end.astimezone(UTC)


def loaded_hours(control) -> dict[str, set[datetime]]:
    out: dict[str, set[datetime]] = {}
    for path, (_, _, status) in control.ledger().items():
        m = HOUR_RE.match(path)
        if m and status in ("loaded", "duplicate"):
            out.setdefault(m.group(1), set()).add(datetime.strptime(m.group(2), "%Y-%m-%dT%H").replace(tzinfo=UTC))
    return out


def closing_months(wh, settings: Settings, as_of: datetime) -> list[tuple[str, str, str, str]]:
    """(partner, month, currency, tz) for every month that has ended in the partner's time zone."""
    first = settings.section("invoicing")["first_month"]
    out = []
    for pid, cur, tz in wh.q("select partner_id, currency, billing_tz from partners order by partner_id"):
        local = as_of.astimezone(ZoneInfo(tz))
        y, m = local.year, local.month
        months = [mo for (mo,) in wh.q("select distinct month from mart_invoice_lines where partner_id = ?", [pid])]
        for mo in sorted(months):
            if first <= mo < f"{y:04d}-{m:02d}":
                out.append((pid, mo, cur, tz))
    return out


def blocking_checks(wh, control, settings: Settings, as_of: datetime) -> list[CheckResult]:
    res: list[CheckResult] = []
    hours = loaded_hours(control)
    first_hour = {b: min(h) for b, h in hours.items() if h}
    carried = {(p, b) for p, b in wh.q("select distinct partner_id, brand from stg_clicks")}
    for pid, mo, _cur, tz in closing_months(wh, settings, as_of):
        scope = f"{pid}/{mo}"
        s, e = month_window_utc(mo, tz)
        missing = []
        for brand, start in first_hour.items():
            if (pid, brand) not in carried:
                continue
            h = max(s, start)
            while h < e:
                if h not in hours[brand]:
                    missing.append(f"{brand} {h:%m-%d %H}h")
                h += timedelta(hours=1)
        res.append(CheckResult("files_complete", scope, "fail" if missing else "pass", len(missing), 0, True,
                               ", ".join(missing[:6]) + (" ..." if len(missing) > 6 else "")))
        if settings.on("quarantine_unknown_values"):
            (n,) = wh.q("select count(*) from stg_quarantine where partner_id = ? and ts >= ? and ts < ?",
                        [pid, s, e])[0]
            res.append(CheckResult("values_in_contract", scope, "fail" if n else "pass", n, 0, True,
                                   f"{n} clicks hold values the brand's schema contract does not list" if n else ""))
        clicks, amount, unpriced = wh.q(
            """select coalesce(sum(clicks), 0), coalesce(sum(amount_minor), 0), coalesce(sum(unpriced), 0)
               from mart_invoice_lines where partner_id = ? and month = ?""", [pid, mo])[0]
        res.append(CheckResult("every_click_priced", scope, "fail" if unpriced else "pass", unpriced, 0, True,
                               f"{unpriced} billable clicks have no rate" if unpriced else ""))
        fc, fa = wh.q("""select count(*), coalesce(sum(price_minor), 0) from fct_billable_clicks
                         where partner_id = ? and month = ?""", [pid, mo])[0]
        ok = fc == clicks and fa == amount
        res.append(CheckResult("lines_match_fact", scope, "pass" if ok else "fail", amount - fa, 0, True,
                               "" if ok else f"lines {clicks}/{amount} vs fact {fc}/{fa}"))
    return res


def monitoring_checks(wh, control, settings: Settings, as_of: datetime) -> list[CheckResult]:
    c = settings.section("checks")
    res: list[CheckResult] = []
    hours = loaded_hours(control)
    today = as_of.astimezone(UTC).date()
    days = [today - timedelta(days=k) for k in (1, 2, 3)]
    vol = {(b, d): n for b, d, n in wh.q(
        "select brand, cast(ts as date) as d, count(*) from stg_clicks group by brand, cast(ts as date)")}
    dup = {(b, d): (n, k) for b, d, n, k in wh.q(
        """select brand, cast(ts as date), count(*), count(*) - count(distinct click_id)
           from stg_clicks where market is not null and device is not null group by brand, cast(ts as date)""")}
    inv = {(b, d): (n, k) for b, d, n, k in wh.q(
        """select brand, cast(ts as date), count(*), count(invalid_reason)
           from int_clicks_scored group by brand, cast(ts as date)""")}
    quar = {(b, d): n for b, d, n in wh.q(
        "select brand, cast(ts as date), count(*) from stg_quarantine group by brand, cast(ts as date)")}
    for b in sorted(hours):
        for d in days:
            if d < min(hours[b]).date():
                continue
            scope = f"{b}/{d}"
            have = sum(1 for h in range(24) if datetime(d.year, d.month, d.day, h, tzinfo=UTC) in hours[b])
            res.append(CheckResult("hourly_files_in", scope, "pass" if have == 24 else "fail", have, 24, False,
                                   "" if have == 24 else f"{24 - have} hourly files missing"))
            prior = [vol.get((b, d - timedelta(weeks=w))) for w in (1, 2, 3)]
            prior = sorted(x for x in prior if x)
            if len(prior) == 3 and (b, d) in vol:
                ratio = vol[(b, d)] / prior[1]
                bad = not (c["volume_ratio_low"] <= ratio <= c["volume_ratio_high"])
                res.append(CheckResult("brand_volume", scope, "fail" if bad else "pass", round(ratio, 3),
                                       c["volume_ratio_high"] if ratio > 1 else c["volume_ratio_low"], False,
                                       f"{ratio:.2f}x the same weekday's median" if bad else ""))
            if (b, d) in dup:
                n, k = dup[(b, d)]
                share = k / n if n else 0.0
                res.append(CheckResult("duplicate_click_ids", scope, "fail" if share > c["duplicate_id_share"] else "pass",
                                       round(share, 4), c["duplicate_id_share"], False,
                                       f"{k} click ids logged more than once" if share > c["duplicate_id_share"] else ""))
            if (b, d) in inv:
                n, k = inv[(b, d)]
                share = k / n if n else 0.0
                res.append(CheckResult("invalid_traffic_share", scope, "fail" if share > c["invalid_share_high"] else "pass",
                                       round(share, 4), c["invalid_share_high"], False,
                                       f"{share:.0%} of clicks broke an invalid-traffic rule" if share > c["invalid_share_high"] else ""))
            q = quar.get((b, d), 0)
            res.append(CheckResult("values_in_contract_daily", scope, "fail" if q else "pass", q, 0, False,
                                   f"{q} clicks with values outside the schema contract" if q else ""))
    # reference rates
    last = wh.q("select max(day) from fx_rates")[0][0]
    bday = _last_business_day(today - timedelta(days=1))
    gap = _business_days_between(last, bday) if last else 99
    res.append(CheckResult("fx_published", f"ecb/{today}", "fail" if gap > c["fx_stale_business_days"] else "pass",
                           gap, c["fx_stale_business_days"], False,
                           f"latest reference rate is from {last}" if gap > c["fx_stale_business_days"] else ""))
    # partner's own counts against what was invoiced
    for pid, mo, reported in wh.q("select partner_id, month, clicks from partner_reports"):
        docs = control.documents(pid, mo)
        if not docs:
            continue
        billed = sum(d[3] for d in docs)
        diff = (billed - reported) / reported if reported else 0.0
        bad = abs(diff) > c["partner_report_tolerance"]
        res.append(CheckResult("partner_count_match", f"{pid}/{mo}", "fail" if bad else "pass", round(diff, 4),
                               c["partner_report_tolerance"], False,
                               f"invoiced {billed} clicks, partner counted {reported}" if bad else ""))
    return res


def _last_business_day(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _business_days_between(a: date, b: date) -> int:
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n
