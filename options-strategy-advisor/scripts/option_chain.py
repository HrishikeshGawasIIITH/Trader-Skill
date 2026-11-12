#!/usr/bin/env python3
"""Live NSE option chain and a rule-based option trade plan. Standard library only, no keys.

    python3 option_chain.py chain DATAPATTNS                       # nearest expiry, calls
    python3 option_chain.py chain NIFTY --side put --expiry 25-Nov-2026
    python3 option_chain.py chain DLF --max-cost 15000 --max-spread 3 --min-oi 500
    python3 option_chain.py plan DLF --strike 760 --side call --stop 748 --target1 772 --target2 784
    python3 option_chain.py plan DLF --strike 760 --stop 748 --target1 772 --target2 784 --write

`chain` lists strikes with bid, ask, spread, implied volatility (IV), open interest,
volume, cost per lot, delta, time decay per lot per day and the breakeven.

`plan` puts the stop and the targets on the STOCK (a chart level), not on the
premium. It estimates the option price at each level with Black-Scholes and the
chain IV, and checks these rules:
  - the loss per lot at the stop is at most --max-loss (config max_loss_per_trade_inr)
  - the cost per lot is at most --max-cost (config max_order_inr)
  - the stop is at least --min-stop-atr ATRs (0.5) from spot, so normal noise does not hit it
  - the spread, the days to expiry, and IV against the 30-day historical volatility
`--write` writes the plan to trader/orders.json for trader-risk. It places nothing.

Data: www.nseindia.com option-chain-contract-info and option-chain-v3 (cookie flow).
NSE gives this data for information. Confirm prices in the broker's option chain.
This is analysis, not financial advice.
"""

import argparse
import http.cookiejar
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from black_scholes import OptionPricer, DEFAULT_RISK_FREE_RATE, fetch_lot_sizes, lot_size  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
INDICES = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}
HOME = "https://www.nseindia.com/option-chain"
INFO_URL = "https://www.nseindia.com/api/option-chain-contract-info?symbol={s}"
CHAIN_URL = "https://www.nseindia.com/api/option-chain-v3?type={t}&symbol={s}&expiry={e}"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/120 Safari/537.36",
           "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9", "Referer": HOME}
TICK = 0.05


class ChainError(Exception):
    pass


class Nse:
    """Cookie session for www.nseindia.com JSON. The home page can answer 403 and still set the cookie."""

    def __init__(self, opener=None, pause=1.0):
        self.op = opener or urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.pause = pause
        self.warm = opener is not None

    def get(self, url):
        if not self.warm:
            try:
                self.op.open(urllib.request.Request(HOME, headers=HEADERS), timeout=20).read()
            except Exception:  # noqa: BLE001 - the cookie is what matters
                pass
            self.warm = True
            time.sleep(self.pause)
        try:
            body = self.op.open(urllib.request.Request(url, headers=HEADERS), timeout=30).read()
        except Exception as e:  # noqa: BLE001
            raise ChainError("NSE did not answer %s: %s" % (url.split("/api/")[-1], e))
        try:
            return json.loads(body or b"null")
        except ValueError:
            raise ChainError("NSE sent something that is not JSON for %s" % url.split("/api/")[-1])


def kind(symbol):
    return "Indices" if symbol.upper() in INDICES else "Equity"


def expiries(nse, symbol):
    doc = nse.get(INFO_URL.format(s=urllib.parse.quote(symbol.upper())))
    out = (doc or {}).get("expiryDates") or []
    if not out:
        raise ChainError("NSE lists no option expiries for %s (is it an F&O stock?)" % symbol)
    return out


def parse_chain(doc, side):
    """option-chain-v3 JSON -> (spot, timestamp, [row]) for one side (CE or PE)."""
    rec = (doc or {}).get("records") or {}
    data = rec.get("data") or []
    key = "CE" if side == "call" else "PE"
    rows, spot = [], _f(rec.get("underlyingValue"))
    for d in data:
        o = d.get(key)
        if not isinstance(o, dict):
            continue
        spot = spot or _f(o.get("underlyingValue"))
        rows.append({"strike": _f(d.get("strikePrice") or o.get("strikePrice")), "bid": _f(o.get("buyPrice1")),
                     "ask": _f(o.get("sellPrice1")), "last": _f(o.get("lastPrice")),
                     "iv": _f(o.get("impliedVolatility")), "oi": int(_f(o.get("openInterest")) or 0),
                     "volume": int(_f(o.get("totalTradedVolume")) or 0)})
    rows = [r for r in rows if r["strike"]]
    rows.sort(key=lambda r: r["strike"])
    return spot, rec.get("timestamp"), rows


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def years_to_expiry(expiry, now):
    """Expiry 'DD-Mon-YYYY' at 15:30 IST -> years from now (at least one minute)."""
    end = datetime.strptime(expiry, "%d-%b-%Y").replace(hour=15, minute=30, tzinfo=IST)
    return max((end - now).total_seconds(), 60) / (365 * 86400)


def price(S, K, T, iv, side, r=DEFAULT_RISK_FREE_RATE):
    g = OptionPricer(S=S, K=K, T=max(T, 1e-6), r=r, sigma=max(iv, 0.01) / 100).get_all_greeks(side)
    return g


def enrich(rows, spot, T, lot, side):
    for r in rows:
        r["mid"] = round((r["bid"] + r["ask"]) / 2, 2) if r["bid"] and r["ask"] else None
        r["spread_pct"] = round((r["ask"] - r["bid"]) / r["mid"] * 100, 1) if r["mid"] else None
        r["cost_lot"] = round(r["ask"] * lot) if r["ask"] and lot else None
        if r["iv"] and spot:
            g = price(spot, r["strike"], T, r["iv"], side)
            r["delta"] = round(g["delta"], 2)
            r["theta_lot_day"] = round(g["theta"] * lot) if lot else None
        else:
            r["delta"] = r["theta_lot_day"] = None
        if r["ask"]:
            r["breakeven"] = round(r["strike"] + r["ask"] if side == "call" else r["strike"] - r["ask"], 2)
        else:
            r["breakeven"] = None
    return rows


def filter_rows(rows, a):
    out = []
    for r in rows:
        if not r["ask"] or not r["bid"]:
            continue
        if a.max_cost and (r["cost_lot"] or 0) > a.max_cost:
            continue
        if a.max_spread is not None and (r["spread_pct"] is None or r["spread_pct"] > a.max_spread):
            continue
        if r["oi"] < a.min_oi:
            continue
        d = abs(r["delta"] or 0)
        if d < a.min_delta or d > a.max_delta:
            continue
        out.append(r)
    return out


def read_config(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def atr_and_hv(symbol):
    """(ATR14, 30-day historical volatility %) from daily bars, or (None, None)."""
    try:
        from india_client import FMPClient
        from black_scholes import yahoo_spot_symbol
        data = FMPClient().get_historical_prices(yahoo_spot_symbol(symbol), days=90) or {}
        bars = list(reversed(data.get("historical") or []))
    except Exception:  # noqa: BLE001
        return None, None
    if len(bars) < 31:
        return None, None
    trs = [max(b["high"] - b["low"], abs(b["high"] - p["close"]), abs(b["low"] - p["close"]))
           for p, b in zip(bars, bars[1:])]
    rets = [math.log(b["close"] / p["close"]) for p, b in zip(bars[-31:], bars[-30:])]
    m = sum(rets) / len(rets)
    hv = math.sqrt(sum((x - m) ** 2 for x in rets) / (len(rets) - 1)) * math.sqrt(252) * 100
    return sum(trs[-14:]) / 14, hv


def tick_down(x):
    return math.floor(x / TICK + 1e-9) * TICK


def tick_up(x):
    return math.ceil(x / TICK - 1e-9) * TICK


def angel_symbol(symbol, expiry, strike, side):
    """Angel One trading symbol, e.g. DLF25NOV26760CE. Confirm it with `angel.py search`."""
    d = datetime.strptime(expiry, "%d-%b-%Y")
    return "%s%s%s%s" % (symbol.upper(), d.strftime("%d%b%y").upper(), "%g" % strike, "CE" if side == "call" else "PE")


def build_plan(row, spot, T, lot, side, a, atr=None, hv=None, symbol="", expiry=""):
    """Pure function: the plan dict with the checks. No network."""
    hold = max(T - a.hold_days / 365.0, 1e-6)
    entry = row["ask"]
    at = lambda S: price(S, row["strike"], hold, row["iv"], side)["price"]  # noqa: E731
    stop_p = tick_down(max(at(a.stop), TICK))
    t1_p = tick_up(at(a.target1))
    t2_p = tick_up(at(a.target2)) if a.target2 else None
    flat_p = at(spot)
    qty = lot * a.lots
    loss = round((entry - stop_p) * qty, 2)
    gain1 = round((t1_p - entry) * qty, 2)
    gain2 = round((t2_p - entry) * qty, 2) if t2_p else None
    bad, warn = [], []
    if side == "call" and not (a.stop < spot < a.target1):
        bad.append("for a call the stock stop must be under spot and the target above it")
    if side == "put" and not (a.stop > spot > a.target1):
        bad.append("for a put the stock stop must be above spot and the target under it")
    if loss > a.max_loss:
        bad.append("loss at the stop is Rs %s, over the Rs %s limit: pick a cheaper strike or a closer chart level"
                   % (_m(loss), _m(a.max_loss)))
    if a.max_cost and entry * qty > a.max_cost:
        bad.append("cost Rs %s is over the Rs %s limit" % (_m(entry * qty), _m(a.max_cost)))
    if atr:
        dist = abs(spot - a.stop) / atr
        if dist < a.min_stop_atr:
            bad.append("the stop is %.2f ATR from spot, under %.2f ATR: normal noise can hit it" % (dist, a.min_stop_atr))
    if row["spread_pct"] is not None and row["spread_pct"] > a.max_spread:
        warn.append("spread %.1f%% is wide; a limit order may not fill" % row["spread_pct"])
    days = T * 365
    if days < 3:
        warn.append("%.1f days to expiry: time decay is fast" % days)
    if hv and row["iv"] and row["iv"] - hv > 10:
        warn.append("IV %.1f%% is %.1f points over the 30-day volatility %.1f%%: the option is expensive"
                    % (row["iv"], row["iv"] - hv, hv))
    if gain1 <= 0:
        bad.append("the first target does not make money at this strike")
    plan = {"symbol": symbol, "expiry": expiry, "side": side, "strike": row["strike"], "lot": lot, "lots": a.lots,
            "spot": spot, "iv": row["iv"], "hv30": round(hv, 1) if hv else None, "atr14": round(atr, 2) if atr else None,
            "entry": entry, "cost": round(entry * qty, 2),
            "stock_levels": {"stop": a.stop, "target1": a.target1, "target2": a.target2},
            "premium_levels": {"stop": round(stop_p, 2), "target1": round(t1_p, 2),
                               "target2": round(t2_p, 2) if t2_p else None},
            "loss_at_stop": loss, "gain_at_target1": gain1, "gain_at_target2": gain2,
            "reward_risk": round((gain2 or gain1) / loss, 2) if loss > 0 else None,
            "theta_lot_day": row.get("theta_lot_day"),
            "loss_if_flat_for_hold": round((entry - flat_p) * qty, 2), "hold_days": a.hold_days,
            "ok": not bad, "blocks": bad, "warnings": warn}
    return plan


def order_from(plan, product):
    sym = angel_symbol(plan["symbol"], plan["expiry"], plan["strike"], plan["side"])
    pl = plan["premium_levels"]
    return {"symbol": sym, "exchange": "NFO", "product": product, "side": "buy",
            "qty": str(plan["lot"] * plan["lots"]), "type": "limit", "time_in_force": "day",
            "limit_price": "%.2f" % plan["entry"], "order_class": "bracket",
            "stop_loss_stop_price": "%.2f" % pl["stop"],
            "take_profit_limit_price": "%.2f" % (pl["target2"] or pl["target1"]),
            "plan": {"underlying": plan["symbol"], "stock_stop": plan["stock_levels"]["stop"],
                     "stock_target1": plan["stock_levels"]["target1"],
                     "stock_target2": plan["stock_levels"]["target2"], "premium_target1": "%.2f" % pl["target1"]},
            "why": "option plan: stock stop %g, targets %g/%s, loss at stop Rs %s" % (
                plan["stock_levels"]["stop"], plan["stock_levels"]["target1"],
                "%g" % plan["stock_levels"]["target2"] if plan["stock_levels"]["target2"] else "-",
                _m(plan["loss_at_stop"]))}


def _m(x):
    return "{:,.0f}".format(x)


def load(a, nse):
    sym = a.symbol.upper()
    if a.offline:
        with open(a.offline, encoding="utf-8") as fh:
            doc = json.load(fh)
        exp = a.expiry or (doc.get("records") or {}).get("expiryDates", [None])[0]
    else:
        exp = a.expiry or expiries(nse, sym)[0]
        doc = nse.get(CHAIN_URL.format(t=kind(sym), s=urllib.parse.quote(sym), e=exp))
    spot, ts, rows = parse_chain(doc, a.side)
    if not rows or not spot:
        raise ChainError("NSE sent no %s rows for %s %s" % (a.side, sym, exp))
    lot = a.lot or lot_size(sym, fetch_lot_sizes())
    if not lot:
        raise ChainError("no lot size for %s in NSE's F&O file; pass --lot" % sym)
    now = datetime.strptime(a.now, "%Y-%m-%d %H:%M").replace(tzinfo=IST) if a.now else datetime.now(IST)
    T = years_to_expiry(exp, now)
    return sym, exp, spot, ts, lot, T, enrich(rows, spot, T, lot, a.side)


def cmd_chain(a, nse):
    sym, exp, spot, ts, lot, T, rows = load(a, nse)
    keep = filter_rows(rows, a)
    if a.json:
        print(json.dumps({"symbol": sym, "expiry": exp, "spot": spot, "timestamp": ts, "lot": lot,
                          "days_to_expiry": round(T * 365, 2), "rows": keep}, indent=2))
        return 0 if keep else 1
    print("%s %s %s, spot %s, lot %d, %.1f days to expiry. NSE data at %s." % (
        sym, exp, "calls" if a.side == "call" else "puts", spot, lot, T * 365, ts))
    print("Filters: cost per lot <= %s, spread <= %s%%, OI >= %d, |delta| %.2f to %.2f." % (
        "Rs %s" % _m(a.max_cost) if a.max_cost else "any", a.max_spread, a.min_oi, a.min_delta, a.max_delta))
    if not keep:
        print("No strike passes the filters.")
        return 1
    print("  strike      bid      ask  spread    IV     OI    volume  cost/lot  delta  decay/day  breakeven")
    for r in keep:
        print("  %6g %8.2f %8.2f %6.1f%% %5.1f %6d %9d %9s %6.2f %10s %10.2f" % (
            r["strike"], r["bid"], r["ask"], r["spread_pct"], r["iv"] or 0, r["oi"], r["volume"],
            _m(r["cost_lot"]), r["delta"] or 0, _m(r["theta_lot_day"] or 0), r["breakeven"]))
    print("Next: pick a strike, then `option_chain.py plan %s --strike K --stop S --target1 T1 --target2 T2`." % sym)
    return 0


def cmd_plan(a, nse):
    cfg = read_config(a.config)
    if a.max_loss is None:
        a.max_loss = float(cfg.get("max_loss_per_trade_inr") or cfg.get("max_loss_per_trade_usd") or 500)
    if a.max_cost is None:
        a.max_cost = float(cfg.get("max_order_inr") or cfg.get("max_order_usd") or 0) or None
    sym, exp, spot, ts, lot, T, rows = load(a, nse)
    row = next((r for r in rows if abs(r["strike"] - a.strike) < 1e-6), None)
    if not row or not row["ask"] or not row["iv"]:
        raise ChainError("strike %g has no ask or no IV in the chain" % a.strike)
    atr, hv = (a.atr, None) if a.atr else (atr_and_hv(sym) if not a.offline else (None, None))
    plan = build_plan(row, spot, T, lot, a.side, a, atr, hv, sym, exp)
    plan["nse_timestamp"] = ts
    if a.json:
        print(json.dumps(plan, indent=2))
    else:
        pl, sl = plan["premium_levels"], plan["stock_levels"]
        print("%s %s %g %s, lot %d x %d, spot %s, IV %.1f%%%s%s." % (
            sym, exp, a.strike, "CE" if a.side == "call" else "PE", lot, a.lots, spot, row["iv"],
            ", HV30 %.1f%%" % hv if hv else "", ", ATR14 %.2f" % atr if atr else ""))
        print("  entry (ask)  %8.2f   cost Rs %s" % (plan["entry"], _m(plan["cost"])))
        print("  stop         %8.2f   when the stock reaches %g: loss Rs %s" % (pl["stop"], sl["stop"], _m(plan["loss_at_stop"])))
        print("  target 1     %8.2f   when the stock reaches %g: gain Rs %s" % (pl["target1"], sl["target1"], _m(plan["gain_at_target1"])))
        if pl["target2"]:
            print("  target 2     %8.2f   when the stock reaches %g: gain Rs %s" % (pl["target2"], sl["target2"], _m(plan["gain_at_target2"])))
        print("  time decay about Rs %s a lot a day; flat stock for %g day(s) costs Rs %s" % (
            _m(abs(plan["theta_lot_day"] or 0)), a.hold_days, _m(plan["loss_if_flat_for_hold"])))
        for b in plan["blocks"]:
            print("  BLOCK: " + b)
        for w in plan["warnings"]:
            print("  note: " + w)
        print("PLAN OK: it fits your limits." if plan["ok"] else "PLAN REJECTED: fix the BLOCK lines first.")
        print("Option prices at the levels are Black-Scholes estimates at the chain IV. A gap can skip a stop.")
    if a.write and plan["ok"]:
        order = order_from(plan, a.product)
        os.makedirs(os.path.dirname(a.write) or ".", exist_ok=True)
        with open(a.write, "w", encoding="utf-8") as fh:
            json.dump({"created_by": "options-strategy-advisor", "orders": [order]}, fh, indent=2)
        print("Wrote %s (1 order, symbol %s). Confirm the symbol with `angel.py search %s --exchange NFO`,"
              " then run trader-risk." % (a.write, order["symbol"], sym))
    elif a.write:
        print("Nothing written: the plan is rejected.")
    return 0 if plan["ok"] else 1


def main(argv=None, nse=None):
    ap = argparse.ArgumentParser(description="NSE option chain and option trade plan (information only).")
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("symbol")
        p.add_argument("--side", choices=("call", "put"), default="call")
        p.add_argument("--expiry", help="DD-Mon-YYYY, default the nearest")
        p.add_argument("--lot", type=int, help="lot size (default from NSE's F&O file)")
        p.add_argument("--max-spread", type=float, default=3.0, help="max bid-ask spread %% (3)")
        p.add_argument("--now", help='pin the clock, "YYYY-MM-DD HH:MM" IST')
        p.add_argument("--offline", metavar="FILE", help="a saved option-chain-v3 JSON")
        p.add_argument("--config", default="trader/config.json")
        p.add_argument("--json", action="store_true")

    p = sub.add_parser("chain", help="list strikes that pass the filters")
    common(p)
    p.add_argument("--max-cost", type=float, default=None, help="max cost per lot in rupees")
    p.add_argument("--min-oi", type=int, default=100)
    p.add_argument("--min-delta", type=float, default=0.2)
    p.add_argument("--max-delta", type=float, default=0.7)
    p = sub.add_parser("plan", help="levels and checks for one strike")
    common(p)
    p.add_argument("--strike", type=float, required=True)
    p.add_argument("--stop", type=float, required=True, help="stop level on the STOCK (a chart level)")
    p.add_argument("--target1", type=float, required=True, help="first target on the stock")
    p.add_argument("--target2", type=float, help="final target on the stock")
    p.add_argument("--lots", type=int, default=1)
    p.add_argument("--max-loss", type=float, default=None, help="default config max_loss_per_trade_inr")
    p.add_argument("--max-cost", type=float, default=None, help="default config max_order_inr")
    p.add_argument("--min-stop-atr", type=float, default=0.5)
    p.add_argument("--atr", type=float, help="ATR14 of the stock (default from daily bars)")
    p.add_argument("--hold-days", type=float, default=0.25, help="time until the stop or target hits (0.25)")
    p.add_argument("--product", choices=("intraday", "carryforward"), default="intraday")
    p.add_argument("--write", nargs="?", const="trader/orders.json", default=None,
                   help="write the order to trader/orders.json (or FILE) when the plan is OK")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"chain": cmd_chain, "plan": cmd_plan}[a.cmd](a, nse or Nse())
    except ChainError as e:
        print("option_chain.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    sys.exit(main())
