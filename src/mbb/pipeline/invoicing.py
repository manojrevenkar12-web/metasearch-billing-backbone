"""Invoice documents. An invoice is issued once; any later change is an adjustment note, never an overwrite."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .checks import CheckResult, closing_months
from .settings import Settings


@dataclass
class InvoiceAction:
    partner_id: str
    month: str
    action: str  # issued, adjusted, held, unchanged
    amount_minor: int
    detail: str = ""


def run_invoicing(wh, control, settings: Settings, as_of: datetime, checks: list[CheckResult]) -> list[InvoiceAction]:
    inv = settings.section("invoicing")
    failing: dict[str, list[str]] = {}
    for c in checks:
        if c.blocking and c.status == "fail":
            failing.setdefault(c.scope, []).append(c.name)
    actions = []
    for pid, mo, cur, tz in closing_months(wh, settings, as_of):
        y, m = map(int, mo.split("-"))
        due = datetime(y + (m == 12), m % 12 + 1, inv["issue_from_day"], 6, tzinfo=ZoneInfo("UTC"))
        if as_of < due:
            continue
        local_day = as_of.astimezone(ZoneInfo(tz)).day
        over_limit = local_day > inv["hold_limit_day"] or as_of.month != due.month
        open_checks = failing.get(f"{pid}/{mo}", [])
        clicks, amount = wh.q("""select coalesce(sum(clicks), 0), coalesce(sum(amount_minor), 0)
                                 from mart_invoice_lines where partner_id = ? and month = ?""", [pid, mo])[0]
        docs = control.documents(pid, mo)
        held = settings.on("hold_invoices") and open_checks and not over_limit
        if not docs:
            if held:
                actions.append(InvoiceAction(pid, mo, "held", amount, ", ".join(open_checks)))
                continue
            control.issue(f"{pid}-{mo}-1", pid, mo, "invoice", 1, cur, int(clicks), int(amount), as_of,
                          ", ".join(open_checks), "mart_invoice_lines")
            actions.append(InvoiceAction(pid, mo, "issued", int(amount), ", ".join(open_checks)))
            continue
        if not settings.on("adjustment_notes"):
            continue
        billed_clicks = sum(d[3] for d in docs)
        billed = sum(d[4] for d in docs)
        diff = int(amount) - billed
        if abs(diff) < inv["adjustment_min_minor"]:
            continue
        if held:
            actions.append(InvoiceAction(pid, mo, "held", diff, "adjustment waits: " + ", ".join(open_checks)))
            continue
        v = len(docs) + 1
        kind = "credit_note" if diff < 0 else "debit_note"
        control.issue(f"{pid}-{mo}-{v}", pid, mo, kind, v, cur, int(clicks) - billed_clicks, diff, as_of,
                      ", ".join(open_checks), "mart_invoice_lines")
        actions.append(InvoiceAction(pid, mo, "adjusted", diff, kind))
    return actions
