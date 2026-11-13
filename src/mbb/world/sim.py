"""The simulated metasearch: brands ship redirect logs, partners pay per click.

The world writes two things that never mix:

* ``landing/``: what the company receives, each object with the time it arrives (``arrivals.jsonl``);
* ``truth/``: what really happened: which clicks were billable, at what price, and the true reference rates.

Only ``scripts/evaluate.py`` and the demo command read ``truth/``; a test checks that nothing in the
pipeline imports this package.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import shutil
import tomllib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

UTC = timezone.utc
HOUR_PROFILE = np.array(  # share of a market's clicks per local hour
    [0.8, 0.5, 0.3, 0.2, 0.2, 0.3, 0.8, 1.5, 2.2, 2.8, 3.1, 3.3, 3.4, 3.4, 3.3, 3.3, 3.5, 3.9, 4.4, 4.9, 5.2, 4.8,
     3.6, 2.0])
WEEKDAY = np.array([1.05, 1.0, 0.98, 1.0, 0.96, 0.88, 1.12])  # Mon..Sun
HUMAN_UA = {
    "desktop": ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0", "Mozilla/5.0 (Macintosh) Safari/18.1",
                "Mozilla/5.0 (X11; Linux x86_64) Firefox/133.0"],
    "mobile": ["Mozilla/5.0 (iPhone; CPU iPhone OS 18_1) Mobile/15E148", "Mozilla/5.0 (Linux; Android 15) Chrome/131.0 Mobile"],
    "tablet": ["Mozilla/5.0 (iPad; CPU OS 18_1) Mobile/15E148", "Mozilla/5.0 (Linux; Android 14; Tab) Chrome/131.0"],
}
HEADLESS_UA = ["Mozilla/5.0 HeadlessChrome/131.0", "python-requests/2.32", "Mozilla/5.0 (compatible; PriceWatchBot/3.2)"]
MONITOR_UA = "KAYAK-SyntheticMonitor/2.1 (+internal)"
FIELDS = ["click_id", "search_id", "session_id", "offer_id", "brand", "partner_id", "market", "device", "ts", "ip",
          "user_agent", "asn_type", "search_to_click_ms"]


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def load_config(path: str | Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


@dataclass
class World:
    cfg: dict
    root: Path
    rng: np.random.Generator = field(init=False)

    def __post_init__(self):
        self.rng = np.random.default_rng(self.cfg["seed"])
        self.start = date.fromisoformat(self.cfg["start"])
        self.partners = self.cfg["partners"]
        self.pid_index = {p["id"]: i for i, p in enumerate(self.partners)}
        self.markets = list(self.cfg["markets"])
        self.devices = list(self.cfg["devices"])
        self.arrivals: list[dict] = []
        self.incidents = self.cfg.get("incidents", [])

    # ---------------------------------------------------------------- landing-zone writes
    def _put(self, logical: str, data: bytes, arrival: datetime, version: str = "v1") -> None:
        obj = f"objects/{version}/{logical}"
        p = self.root / "landing" / obj
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        self.arrivals.append({"path": logical, "object": obj, "arrival": arrival.isoformat()})

    # ---------------------------------------------------------------- contracts and rates
    def rate_card(self) -> dict[tuple, int]:
        fx0 = {c: v[0] for c, v in self.cfg["fx"].items()} | {"EUR": 1.0}
        card = {}
        for p in self.partners:
            base = self.cfg["verticals"][p["vertical"]]["cpc"]
            for m, (_, _, mm) in self.cfg["markets"].items():
                for d, (_, dm) in self.cfg["devices"].items():
                    card[(p["id"], m, d)] = int(round(base * mm * dm * p["factor"] * fx0[p["currency"]]))
        return card

    def write_contracts(self, card: dict) -> list[dict]:
        t0 = datetime.combine(self.start, datetime.min.time(), UTC) - timedelta(days=3)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["partner_id", "name", "vertical", "currency", "billing_tz", "repeat_window_s"])
        for p in self.partners:
            w.writerow([p["id"], p["name"], p["vertical"], p["currency"], p["tz"], p["window"]])
        self._put("contracts/partners.csv", buf.getvalue().encode(), t0)
        self._put("contracts/rate_card_2026-09-01.csv", self._card_csv(card, "2026-01-01"), t0)
        versions = [{"valid_from": "2026-01-01", "recorded": t0, "card": dict(card)}]
        for inc in self.incidents:
            if inc["kind"] != "amendment":
                continue
            rows = {}
            for (pid, m, d), cpc in card.items():
                if pid == inc["partner"] and m in inc["markets"] and d in inc["devices"]:
                    rows[(pid, m, d)] = int(round(cpc * (1 + inc["change"])))
            rec = parse_ts(inc["recorded"])
            name = f"contracts/rate_card_amendment_{inc['partner']}_{rec:%Y%m%dT%H%M}.csv"
            self._put(name, self._card_csv(rows, inc["effective"]), rec)
            versions.append({"valid_from": inc["effective"], "recorded": rec, "card": rows})
        for b in self.cfg["brands"]:
            schema = {"device": self.devices, "market": self.markets}
            self._put(f"contracts/schema_{b}_v1.json", json.dumps(schema).encode(), t0)
        for inc in self.incidents:
            if inc["kind"] == "enum_drift":
                schema = {"device": self.devices, "market": self.markets}
                schema[inc["field"]] = schema[inc["field"]] + [inc["new"]]
                schema.setdefault("aliases", {})[inc["field"]] = {inc["new"].lower(): inc["old"]}
                self._put(f"contracts/schema_{inc['brand']}_v2.json", json.dumps(schema).encode(),
                          parse_ts(inc["contract_arrives"]))
        return versions

    @staticmethod
    def _card_csv(rows: dict, valid_from: str) -> bytes:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["partner_id", "market", "device", "cpc_minor", "valid_from"])
        for (pid, m, d), cpc in sorted(rows.items()):
            w.writerow([pid, m, d, cpc, valid_from])
        return buf.getvalue().encode()

    # ---------------------------------------------------------------- FX
    def write_fx(self) -> dict[str, dict[str, float]]:
        days = self.cfg["days"] + 12
        delay = [i for i in self.incidents if i["kind"] == "fx_delay"]
        true: dict[str, dict[str, float]] = {}
        level = {c: v[0] for c, v in self.cfg["fx"].items()}
        for k in range(-5, days):
            d = self.start + timedelta(days=k)
            if d.weekday() >= 5:
                continue
            for c, (_, vol) in self.cfg["fx"].items():
                level[c] *= float(np.exp(self.rng.normal(0, vol)))
            rates = {c: round(v, 4) for c, v in level.items()}
            true[d.isoformat()] = rates
            arrival = datetime.combine(d, datetime.min.time(), UTC) + timedelta(hours=15, minutes=5)
            for inc in delay:
                if inc["first"] <= d.isoformat() <= inc["last"]:
                    arrival = parse_ts(inc["arrives"])
            body = "currency,rate\n" + "".join(f"{c},{r}\n" for c, r in rates.items())
            self._put(f"fx/ecb_{d.isoformat()}.csv", body.encode(), arrival)
        return true

    # ---------------------------------------------------------------- traffic
    def _market_offsets(self, d: date) -> dict[str, int]:
        noon = datetime.combine(d, datetime.min.time(), UTC) + timedelta(hours=12)
        return {m: int(noon.astimezone(ZoneInfo(v[1])).utcoffset().total_seconds() // 3600)
                for m, v in self.cfg["markets"].items()}

    def _partner_weights(self) -> dict[str, np.ndarray]:
        out = {}
        vshare = {"flight": 0.55, "hotel": 0.35, "car": 0.10}
        for b in self.cfg["brands"]:
            w = np.zeros(len(self.partners))
            for i, p in enumerate(self.partners):
                v = self.cfg["verticals"][p["vertical"]]
                w[i] = vshare[p["vertical"]] * v["brands"][b] * (1.0 / (1 + 0.15 * (i % 6)))
            out[b] = w / w.sum()
        return out

    def generate(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)
        (self.root / "truth").mkdir(parents=True)
        card = self.rate_card()
        versions = self.write_contracts(card)
        fx_true = self.write_fx()
        pw = self._partner_weights()
        rng = self.rng
        tr = self.cfg["traffic"]
        mshare = np.array([v[0] for v in self.cfg["markets"].values()])
        mshare /= mshare.sum()
        dshare = np.array([v[0] for v in self.cfg["devices"].values()])
        dshare /= dshare.sum()
        nat_prefixes = [f"10.{40 + i}.{i * 7 % 250}" for i in range(12)]
        bot_prefixes = [f"185.{20 + i}.{(i * 37) % 250}" for i in range(40)]
        events: list[dict] = []  # true events
        emitted: dict[tuple, list[dict]] = {}  # (brand, utc hour) -> rows as the brand logs them
        click_seq = 0

        def new_id() -> str:
            nonlocal click_seq
            click_seq += 1
            return hashlib.blake2b(f"{self.cfg['seed']}-{click_seq}".encode(), digest_size=8).hexdigest()

        brands = self.cfg["brands"]
        hum_ua = {dv: np.array(v) for dv, v in HUMAN_UA.items()}
        for k in range(self.cfg["days"]):
            d = self.start + timedelta(days=k)
            day0 = datetime.combine(d, datetime.min.time(), UTC)
            offs = self._market_offsets(d)
            n_h = int(self.cfg["clicks_per_day"] * WEEKDAY[d.weekday()] * np.exp(rng.normal(0, 0.04)))
            n_b = int(n_h * tr["bot_share"] / (1 - tr["bot_share"]))
            n_m = int(n_h * tr["monitor_share"])
            n = n_h + n_b + n_m
            kind = np.array(["human"] * n_h + ["bot"] * n_b + ["monitor"] * n_m)
            bi = rng.choice(len(brands), size=n, p=self.cfg["brand_share"])
            pi = np.empty(n, dtype=int)
            for j, b in enumerate(brands):
                sel = bi == j
                pi[sel] = rng.choice(len(self.partners), size=int(sel.sum()), p=pw[b])
            mi = rng.choice(len(self.markets), size=n, p=mshare)
            di = rng.choice(len(self.devices), size=n, p=dshare)
            hour = np.empty(n, dtype=int)
            for j, m in enumerate(self.markets):
                sel = mi == j
                prof = np.roll(HOUR_PROFILE, offs[m])
                hour[sel] = rng.choice(24, size=int(sel.sum()), p=prof / prof.sum())
            mon = kind == "monitor"
            hour[mon] = rng.integers(24, size=int(mon.sum()))
            secs = hour * 3600 + rng.uniform(0, 3600, size=n)
            crude = rng.random(n) < tr["bot_crude_share"]
            nat = rng.random(n) < tr["nat_share"]
            sig = rng.random((n, 3)) < 0.55
            sig[np.arange(n), rng.integers(3, size=n)] = True  # a crude bot shows at least one signal
            repeat = (kind == "human") & (rng.random(n) < tr["repeat_click_share"])
            gaps = rng.uniform(2, 120, size=n)
            s2c_h = np.exp(rng.normal(np.log(9000), 0.8, size=n)).astype(int)
            s2c_b = np.exp(rng.normal(np.log(6500), 0.65, size=n)).astype(int)
            fast = rng.uniform(40, 240, size=n).astype(int)
            sess = rng.integers(1, 10**12, size=n)
            offer = rng.integers(1, 10**7, size=n)
            mobile_asn = rng.random(n) < 0.6
            r1, r2, r3, r4 = (rng.integers(lo, hi, size=n) for lo, hi in ((30, 220), (0, 256), (0, 256), (1, 255)))
            ua_pick = rng.integers(0, 3, size=n)
            for i in range(n):
                dev = self.devices[di[i]]
                kd = kind[i]
                ev = {"kind": str(kd), "brand": brands[bi[i]], "partner_id": self.partners[pi[i]]["id"],
                      "market": self.markets[mi[i]], "device": dev, "ts": day0 + timedelta(seconds=float(secs[i])),
                      "session_id": f"s{sess[i]}", "offer_id": f"o{offer[i]}", "search_id": f"q{sess[i] % 10**9:09d}{i % 1000:03d}"}
                ua_h = str(hum_ua[dev][ua_pick[i] % len(hum_ua[dev])])
                if kd == "human":
                    pre = nat_prefixes[r4[i] % len(nat_prefixes)] if nat[i] else f"{r1[i]}.{r2[i]}.{r3[i]}"
                    ev |= {"ip": f"{pre}.{r4[i]}", "user_agent": ua_h,
                           "asn_type": "mobile" if dev != "desktop" and mobile_asn[i] else "residential",
                           "search_to_click_ms": int(s2c_h[i])}
                elif kd == "monitor":
                    ev |= {"ip": f"34.98.{r4[i] % 4}.{r4[i]}", "user_agent": MONITOR_UA, "asn_type": "datacenter",
                           "search_to_click_ms": 300 + int(r4[i])}
                elif crude[i]:
                    dc, uah, fs = sig[i]
                    ev |= {"ip": f"{bot_prefixes[r2[i] % len(bot_prefixes)]}.{r4[i]}",
                           "user_agent": HEADLESS_UA[ua_pick[i]] if uah else ua_h,
                           "asn_type": "datacenter" if dc else "residential",
                           "search_to_click_ms": int(fast[i]) if fs else int(s2c_b[i]), "stealth": False}
                else:  # residential proxies, real browsers, human pace: not separable from people by these logs
                    ev |= {"ip": f"{r1[i]}.{r2[i]}.{r3[i]}.{r4[i]}", "user_agent": ua_h, "asn_type": "residential",
                           "search_to_click_ms": int(s2c_b[i]), "stealth": True}
                ev["click_id"] = new_id()
                events.append(ev)
                if repeat[i]:
                    rep = dict(ev)
                    rep["click_id"] = new_id()
                    rep["ts"] = ev["ts"] + timedelta(seconds=float(gaps[i]))
                    rep["repeat_of_gap"] = float(gaps[i])
                    events.append(rep)
            for inc in self.incidents:
                if inc["kind"] != "bot_storm":
                    continue
                s, e = parse_ts(inc["start"]), parse_ts(inc["end"])
                if not (s <= day0 < e):
                    continue
                hotels = [p["id"] for p in self.partners if p["vertical"] == "hotel"]
                for _ in range(inc["per_day"]):
                    ts = day0 + timedelta(seconds=float(rng.uniform(0, 86400)))
                    ip = f"{bot_prefixes[int(rng.integers(6))]}.{int(rng.integers(1, 255))}"
                    ev = {"kind": "bot", "brand": inc["brand"], "partner_id": hotels[int(rng.integers(len(hotels)))],
                          "market": inc["market"], "device": "desktop", "ts": ts, "ip": ip,
                          "user_agent": HUMAN_UA["desktop"][0],
                          "asn_type": "datacenter" if rng.random() < 0.5 else "residential",
                          "search_to_click_ms": int(rng.uniform(60, 400)), "search_id": hashlib.md5(
                              str(rng.random()).encode()).hexdigest()[:12],
                          "session_id": f"s{int(rng.integers(1e9))}", "offer_id": f"o{int(rng.integers(1e6))}",
                          "click_id": new_id(), "storm": True}
                    events.append(ev)

        # truth: billable and price
        win = {p["id"]: p["window"] for p in self.partners}
        ptz = {p["id"]: ZoneInfo(p["tz"]) for p in self.partners}
        for ev in events:
            ev["billable"] = ev["kind"] == "human" and not ("repeat_of_gap" in ev and ev["repeat_of_gap"] < win[ev["partner_id"]])
            local = ev["ts"].astimezone(ptz[ev["partner_id"]])
            ev["local_date"] = local.date().isoformat()
            ev["bill_month"] = local.strftime("%Y-%m")
            cpc = 0
            for v in versions:  # final contract: latest valid_from that applies, later records win
                if v["valid_from"] <= ev["local_date"] and (ev["partner_id"], ev["market"], ev["device"]) in v["card"]:
                    cpc = v["card"][(ev["partner_id"], ev["market"], ev["device"])]
            ev["list_price_minor"] = cpc  # what the click would cost if billed
            ev["price_minor"] = cpc if ev["billable"] else 0

        # emission: what each brand logs, hour by hour
        for ev in events:
            row = self._row(ev)
            emitted.setdefault((ev["brand"], ev["ts"].replace(minute=0, second=0, microsecond=0)), []).append(row)
            for inc in self.incidents:
                if (inc["kind"] == "double_firing" and ev["brand"] == inc["brand"] and ev["device"] == inc["device"]
                        and parse_ts(inc["start"]) <= ev["ts"] < parse_ts(inc["end"])):
                    dup = dict(row)
                    dup["ts"] = _iso(ev["ts"] + timedelta(seconds=float(rng.uniform(0.3, 3.0))))
                    emitted[(ev["brand"], ev["ts"].replace(minute=0, second=0, microsecond=0))].append(dup)
        for inc in self.incidents:
            if inc["kind"] == "enum_drift":
                s = parse_ts(inc["start"])
                for (b, hour), rows in emitted.items():
                    if b == inc["brand"] and hour >= s:
                        for r in rows:
                            if r[inc["field"]] == inc["old"]:
                                r[inc["field"]] = inc["new"]
        self._write_click_files(emitted)
        self._write_partner_reports(events)
        self._write_truth(events, fx_true, versions)
        with open(self.root / "landing" / "arrivals.jsonl", "w") as f:
            for a in sorted(self.arrivals, key=lambda a: (a["arrival"], a["path"])):
                f.write(json.dumps(a) + "\n")

    @staticmethod
    def _row(ev: dict) -> dict:
        return {k: (_iso(ev[k]) if k == "ts" else ev[k]) for k in FIELDS}

    def _write_click_files(self, emitted: dict) -> None:
        rng = self.rng
        tr = self.cfg["traffic"]
        first = datetime.combine(self.start, datetime.min.time(), UTC)
        outages = [i for i in self.incidents if i["kind"] == "outage"]
        for b in self.cfg["brands"]:
            for h in range(self.cfg["days"] * 24):
                hour = first + timedelta(hours=h)
                rows = sorted(emitted.get((b, hour), []), key=lambda r: r["ts"])
                logical = f"clicks/{b}/{hour:%Y-%m-%dT%H}.jsonl.gz"
                data = _gz(rows)
                arrival = hour + timedelta(hours=1, minutes=float(rng.uniform(4, 35)))
                for o in outages:
                    if o["brand"] == b and parse_ts(o["start"]) <= hour < parse_ts(o["end"]):
                        arrival = parse_ts(o["arrives"])
                manifest = json.dumps({"rows": len(rows), "sha256": hashlib.sha256(data).hexdigest()}).encode()
                if rows and rng.random() < tr["partial_file_share"]:
                    self._put(logical, _gz(rows[: int(len(rows) * 0.6)]), arrival, "v1")
                    arrival += timedelta(hours=float(rng.uniform(1, 30)))
                    self._put(logical, data, arrival, "v2")
                else:
                    self._put(logical, data, arrival)
                self._put(logical + ".manifest", manifest, arrival)
                if rows and rng.random() < tr["redelivery_share"]:
                    again = arrival + timedelta(hours=float(rng.uniform(2, 20)))
                    self._put(logical.replace(".jsonl.gz", ".r1.jsonl.gz"), data, again)
                    self._put(logical.replace(".jsonl.gz", ".r1.jsonl.gz") + ".manifest", manifest, again)

    def _write_partner_reports(self, events: list[dict]) -> None:
        counts: dict[tuple, int] = {}
        for ev in events:
            if ev["billable"]:
                counts[(ev["partner_id"], ev["bill_month"])] = counts.get((ev["partner_id"], ev["bill_month"]), 0) + 1
        for (pid, month), n in sorted(counts.items()):
            y, mo = map(int, month.split("-"))
            nxt = date(y + (mo == 12), mo % 12 + 1, 5)
            if nxt > self.start + timedelta(days=self.cfg["days"] + 12):
                continue
            reported = int(round(n * (1 + self.rng.normal(0, 0.004))))
            body = f"partner_id,month,clicks\n{pid},{month},{reported}\n"
            self._put(f"partner_reports/{pid}_{month}.csv", body.encode(),
                      datetime.combine(nxt, datetime.min.time(), UTC) + timedelta(hours=12))

    def _write_truth(self, events: list[dict], fx_true: dict, versions: list[dict]) -> None:
        t = self.root / "truth"
        with gzip.open(t / "events.csv.gz", "wt", newline="") as f:
            w = csv.writer(f)
            w.writerow(["click_id", "brand", "partner_id", "market", "device", "ts", "kind", "stealth", "storm",
                        "billable", "local_date", "bill_month", "price_minor", "list_price_minor"])
            for ev in events:
                w.writerow([ev["click_id"], ev["brand"], ev["partner_id"], ev["market"], ev["device"], _iso(ev["ts"]),
                            ev["kind"], int(ev.get("stealth", False)), int(ev.get("storm", False)), int(ev["billable"]),
                            ev["local_date"], ev["bill_month"], ev["price_minor"], ev["list_price_minor"]])
        with open(t / "fx.json", "w") as f:
            json.dump(fx_true, f, indent=0)
        inv: dict[tuple, list[int]] = {}
        for ev in events:
            if ev["billable"]:
                k = (ev["partner_id"], ev["bill_month"])
                inv.setdefault(k, [0, 0])
                inv[k][0] += 1
                inv[k][1] += ev["price_minor"]
        cur = {p["id"]: p["currency"] for p in self.partners}
        with open(t / "invoices.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["partner_id", "month", "currency", "clicks", "amount_minor"])
            for (pid, mo), (n, a) in sorted(inv.items()):
                w.writerow([pid, mo, cur[pid], n, a])
        json.dump({"incidents": self.incidents, "seed": self.cfg["seed"], "name": self.cfg["name"]},
                  open(t / "meta.json", "w"), indent=1)


def _iso(ts: datetime) -> str:
    return ts.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _gz(rows: list[dict]) -> bytes:
    raw = "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows).encode()
    return gzip.compress(raw, mtime=0)


def generate(config: str | Path, root: str | Path) -> Path:
    w = World(load_config(config), Path(root))
    w.generate()
    return Path(root)
