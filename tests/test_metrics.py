import tomllib
from datetime import date
from pathlib import Path

from mbb.metrics.ask import RuleReader, answer
from mbb.metrics.layer import Catalog, Plan

ROOT = Path(__file__).resolve().parent.parent
CAT = Catalog(ROOT / "config" / "metrics.toml")
PARTNERS = {"P01": "Alder Air", "P08": "Wayfarer Travel", "P11": "Brightstay Hotels"}
READER = RuleReader(CAT, PARTNERS, ["cheapflights", "hotelscombined", "kayak", "momondo"],
                    ["DE", "ES", "FR", "GB", "IT", "NL", "SE", "US"], ["desktop", "mobile", "tablet"])


def plan_of(q):
    return dict(metric=q["metric"] or None, by=sorted(q.get("by", [])), filters=q.get("filters", {}),
                start=date.fromisoformat(q["start"]) if q.get("start") else None,
                end=date.fromisoformat(q["end"]) if q.get("end") else None)


def test_reader_matches_the_written_plans():
    qs = tomllib.loads((ROOT / "config" / "questions.toml").read_text())
    today = date.fromisoformat(qs["today"])
    wrong = []
    for q in qs["q"]:
        p = READER.read(q["text"], today)
        refused = CAT.validate(p) is not None
        exp = plan_of(q)
        if exp["metric"] is None:
            ok = refused
        else:
            ok = not refused and dict(metric=p.metric, by=sorted(p.by), filters=p.filters, start=p.start,
                                      end=p.end) == exp
        if not ok:
            wrong.append((q["text"], p))
    assert not wrong, wrong


def test_values_are_bound_never_spliced():
    sql, params = CAT.compile(Plan("billed_clicks", ["brand"], {"partner": "P01'; drop table x; --"}))
    assert "drop" not in sql and params == ["P01'; drop table x; --"]


def test_a_dimension_the_metric_does_not_have_is_refused():
    out = answer("revenue by brand", READER, CAT, lambda s, p: [], date(2026, 11, 10))
    assert out["answered"] is False and "brand" in out["refusal"]
