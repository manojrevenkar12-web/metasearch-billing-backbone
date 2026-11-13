"""Ask the billing data a question in words.

A reader turns the question into a Plan; the catalog checks it and compiles the SQL; the warehouse answers.
The reader can be the rule-based one here (no model, used in the evaluation) or Claude through the
Anthropic API when ANTHROPIC_API_KEY is set. Either way the model only proposes a plan: it never writes SQL,
and a plan outside the certified metrics is refused rather than guessed.
"""

from __future__ import annotations

import json
import os
import re
from calendar import monthrange
from dataclasses import asdict
from datetime import date, timedelta

from .layer import Catalog, Plan

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
     "december"], start=1)}
COUNTRIES = {"germany": "DE", "uk": "GB", "united kingdom": "GB", "britain": "GB", "us": "US", "usa": "US",
             "united states": "US", "america": "US", "france": "FR", "spain": "ES", "italy": "IT",
             "netherlands": "NL", "sweden": "SE"}
DIM_WORDS = {"partner": "partner", "partners": "partner", "advertiser": "partner", "brand": "brand", "brands": "brand",
             "site": "brand", "market": "market", "markets": "market", "country": "market", "countries": "market",
             "device": "device", "devices": "device", "day": "day", "daily": "day", "month": "month",
             "reason": "reason", "rule": "reason", "currency": "currency", "kind": "kind", "type": "kind"}
UNANSWERABLE = ["conversion", "booking", "profit", "margin", "forecast", "predict", "why", "should we", "salary",
                "ctr", "next month"]


class RuleReader:
    def __init__(self, catalog: Catalog, partners: dict[str, str], brands: list[str], markets: list[str],
                 devices: list[str]):
        self.catalog = catalog
        self.partners = {n.lower(): pid for pid, n in partners.items()} | {pid.lower(): pid for pid in partners}
        self.brands = brands
        self.markets = markets
        self.devices = devices

    def read(self, question: str, today: date) -> Plan:
        q = " " + re.sub(r"[?!.,]", " ", question.lower()) + " "
        if any(w in q for w in UNANSWERABLE):
            return Plan(None, refusal="that is not one of the certified metrics; ask the BI team for a new one")
        metric = None
        best = 0
        for name, m in self.catalog.metrics.items():
            for w in m["words"]:
                if f" {w} " in q and len(w) > best:
                    metric, best = name, len(w)
        if metric is None:
            return Plan(None, refusal="no certified metric matches the question")
        plan = Plan(metric)
        for m in re.finditer(r"\b(?:by|per|each|split by|broken down by)\s+(\w+)", q):
            d = DIM_WORDS.get(m.group(1))
            if d and d not in plan.by:
                plan.by.append(d)
        for name, pid in sorted(self.partners.items(), key=lambda x: -len(x[0])):
            if re.search(rf"\b{re.escape(name)}\b", q):
                plan.filters["partner"] = pid
                break
        for b in self.brands:
            if re.search(rf"\b{b}\b", q):
                plan.filters["brand"] = b
        for c, code in sorted(COUNTRIES.items(), key=lambda x: -len(x[0])):
            if re.search(rf"\b(in|from|for)\s+(the\s+)?{c}\b", q):
                plan.filters["market"] = code
                break
        for code in self.markets:
            if re.search(rf"\b{code.lower()}\b", q) and code.lower() not in ("us", "it") or \
                    re.search(rf"\b(market|in)\s+{code.lower()}\b", q):
                plan.filters.setdefault("market", code)
        for d in self.devices:
            if re.search(rf"\b{d}\b", q):
                plan.filters["device"] = d
        self._period(q, today, plan)
        return plan

    @staticmethod
    def _period(q: str, today: date, plan: Plan) -> None:
        for name, num in MONTHS.items():
            if re.search(rf"\b{name}\b", q):
                y = today.year if num <= today.month else today.year - 1
                plan.start, plan.end = date(y, num, 1), date(y, num, monthrange(y, num)[1]) + timedelta(days=1)
                return
        if "yesterday" in q:
            plan.start, plan.end = today - timedelta(days=1), today
        elif "last week" in q:
            monday = today - timedelta(days=today.weekday())
            plan.start, plan.end = monday - timedelta(days=7), monday
        elif "last month" in q:
            first = today.replace(day=1)
            prev = (first - timedelta(days=1)).replace(day=1)
            plan.start, plan.end = prev, first
        elif "this month" in q:
            plan.start, plan.end = today.replace(day=1), today + timedelta(days=1)


class ClaudeReader:
    """Claude proposes the plan through a tool call; the catalog still decides whether it stands."""

    def __init__(self, catalog: Catalog, partners: dict[str, str], model: str | None = None):
        import anthropic

        self.client = anthropic.Anthropic()
        self.catalog = catalog
        self.partners = partners
        self.model = model or os.environ.get("MBB_ASK_MODEL", "claude-haiku-5-5")

    def read(self, question: str, today: date) -> Plan:
        tool = {"name": "plan", "description": "A plan over the certified metrics, or a refusal.",
                "input_schema": {"type": "object", "properties": {
                    "metric": {"type": ["string", "null"], "enum": list(self.catalog.metrics) + [None]},
                    "by": {"type": "array", "items": {"type": "string"}},
                    "filters": {"type": "object", "additionalProperties": {"type": "string"}},
                    "start": {"type": ["string", "null"]}, "end": {"type": ["string", "null"]},
                    "refusal": {"type": ["string", "null"]}}, "required": ["metric"]}}
        system = ("You turn a business question into a plan over certified metrics. Never invent a metric. "
                  f"Today is {today}. Metrics: {json.dumps(self.catalog.metrics)}. "
                  f"Partners: {json.dumps(self.partners)}. Use partner ids, market codes, lowercase brands. "
                  "end is exclusive. If no metric answers the question, set metric to null and give a refusal.")
        msg = self.client.messages.create(model=self.model, max_tokens=400, system=system, tools=[tool],
                                          tool_choice={"type": "tool", "name": "plan"},
                                          messages=[{"role": "user", "content": question}])
        args = next(b.input for b in msg.content if b.type == "tool_use")
        return Plan(args.get("metric"), list(args.get("by") or []), dict(args.get("filters") or {}),
                    date.fromisoformat(args["start"]) if args.get("start") else None,
                    date.fromisoformat(args["end"]) if args.get("end") else None, args.get("refusal"))


def answer(question: str, reader, catalog: Catalog, query, today: date) -> dict:
    plan = reader.read(question, today)
    err = catalog.validate(plan)
    out = {"question": question, "plan": {k: (v.isoformat() if isinstance(v, date) else v)
                                          for k, v in asdict(plan).items()}}
    if err:
        return out | {"answered": False, "refusal": err}
    sql, params = catalog.compile(plan)
    rows = query(sql, params)
    m = catalog.metrics[plan.metric]
    return out | {"answered": True, "metric": m["label"], "unit": m["unit"], "sql": sql,
                  "rows": [[c.isoformat() if hasattr(c, "isoformat") else c for c in r] for r in rows]}


def reader_for(wh, claude: bool = False, catalog_path: str | None = None):
    from pathlib import Path

    path = catalog_path or os.environ.get("MBB_METRICS", str(Path(__file__).resolve().parents[3] / "config" / "metrics.toml"))
    catalog = Catalog(path)
    partners = dict(wh.q("select partner_id, name from partners order by partner_id"))
    if claude:
        return ClaudeReader(catalog, partners), catalog
    brands = [b for (b,) in wh.q("select distinct brand from enum_map order by brand")]
    markets = [m for (m,) in wh.q("select distinct canonical from enum_map where field = 'market' order by 1")]
    devices = [d for (d,) in wh.q("select distinct canonical from enum_map where field = 'device' order by 1")]
    return RuleReader(catalog, partners, brands, markets, devices), catalog
