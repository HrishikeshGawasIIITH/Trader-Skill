#!/usr/bin/env python3
"""Angel One SmartAPI client for trader-broker. Standard library only.

SECRETS: this script reads the Angel One keys from ~/.trader/angel.env (or
environment variables). No agent may open, print, copy or edit that file, or
any .env file. The script never prints a secret. `doctor` only says
"present" or "missing" for each key.

    python angel.py doctor                       # setup check, no secrets shown
    python angel.py login | logout | profile | funds
    python angel.py orders | trades | positions | holdings
    python angel.py search NIFTY --exchange NFO [--expiry 25NOV2026] [--strike 24000] [--type CE]
    python angel.py ltp RELIANCE TCS [--exchange NSE] [--write]
    python angel.py candles RELIANCE --interval FIVE_MINUTE --from "2026-11-11 09:15" --to "2026-11-11 15:30"
    python angel.py margin --index 1 | charges --index 1
    python angel.py place --index 1              # only a READY + approved order; see SKILL.md
    python angel.py protect --index 1            # place the stop-loss for a filled entry
    python angel.py modify --order-id ID [--price P] [--trigger T] [--qty Q]   # risk-reducing changes only
    python angel.py convert --symbol SBIN --side buy --qty 10 --from INTRADAY --to DELIVERY --reply "yes ..."
    python angel.py cancel --order-id ID
    python angel.py kill [--flatten]             # cancel all open orders; --flatten exits intraday positions

Paper mode is the default. Live orders need ALL of: config "paper": false,
config "broker": "angelone", and the environment variable ANGEL_LIVE=1.
"""

import argparse
import base64
import datetime
import hashlib
import hmac
import json
import os
import re
import socket
import struct
import sys
import time
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ticket  # noqa: E402  (same folder: gates, fingerprints, fills, clock)

BASE = "https://apiconnect.angelone.in"
SCRIP_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
HOME = os.path.join(os.path.expanduser("~"), ".trader")
SECRETS_FILE = os.path.join(HOME, "angel.env")
SESSION_FILE = os.path.join(HOME, "angel_session.json")
SCRIPS = os.path.join("trader", "cache", "scrips.json")
AUDIT = os.path.join("trader", "state", "angel_audit.jsonl")
PAPER = os.path.join("trader", "state", "angel_paper.json")
STOP_FILE = os.path.join("trader", "STOP")
KEYS = ("ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_MPIN", "ANGEL_TOTP_SECRET")
SECRET_FIELDS = {"authorization", "x-privatekey", "password", "totp", "jwttoken", "refreshtoken",
                 "feedtoken", "mpin", "api_key", "x-macaddress"}

# Hard limits. The config can lower them, never raise them. Edit here only on purpose.
HARD = {"max_order_value": 25000.0, "max_orders_per_day": 5, "price_band_pct": 2.0,
        "max_strike_distance_pct": 5.0}
SEGMENTS = ("NSE", "BSE", "NFO", "BFO")
FNO = ("NFO", "BFO")
PRODUCTS = {"intraday": "INTRADAY", "delivery": "DELIVERY", "carryforward": "CARRYFORWARD",
            "margin": "MARGIN"}
TYPES = {"limit": "LIMIT", "market": "MARKET", "stop_limit": "STOPLOSS_LIMIT", "stop": "STOPLOSS_MARKET"}
OPEN, CLOSE = datetime.time(9, 15), datetime.time(15, 30)
HOLIDAYS = {  # NSE equity and F&O trading holidays 2026 (NSE holiday API); trader/nse_holidays.json adds more
    "2026-01-15", "2026-01-26", "2026-02-15", "2026-03-03", "2026-03-21", "2026-03-26", "2026-03-31",
    "2026-04-03", "2026-04-14", "2026-05-01", "2026-05-28", "2026-06-26", "2026-08-15", "2026-09-14",
    "2026-10-02", "2026-10-20", "2026-11-08", "2026-11-10", "2026-11-24", "2026-12-25"}
NO_ENTRY_AFTER_EXPIRY_DAY = datetime.time(14, 30)
CAS_START, CAS_END = datetime.time(15, 15), datetime.time(15, 20)
GAP = 1.05  # seconds between API calls (Angel One limits: 1/s for books, 9/s for orders)


class AngelError(Exception):
    pass


# ---------------------------------------------------------------- small helpers

def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None)


def ist(utc):
    return ticket.to_local(utc)


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def mask(obj):
    """Copy of obj with every secret value replaced by ***."""
    if isinstance(obj, dict):
        return {k: ("***" if str(k).lower() in SECRET_FIELDS else mask(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask(x) for x in obj]
    return obj


def audit(event, **kw):
    os.makedirs(os.path.dirname(AUDIT), exist_ok=True)
    rec = {"at": now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"), "event": event}
    rec.update(mask(kw))
    with open(AUDIT, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


def tick_round(price, tick, side):
    """Round to the tick: down for a buy limit, up for a sell limit (never worse for the user)."""
    if tick <= 0:
        return round(price, 2)
    n = price / tick
    n = int(n + 1e-9) if side == "buy" else int(-(-n // 1)) if abs(n - round(n)) > 1e-9 else int(round(n))
    return round(n * tick, 2)


def on_tick(price, tick):
    return tick <= 0 or abs(price / tick - round(price / tick)) < 1e-6


# ---------------------------------------------------------------- secrets and TOTP

def load_secrets():
    """Keys from the environment first, then ~/.trader/angel.env (KEY=value lines)."""
    vals = {k: os.environ.get(k, "") for k in KEYS}
    vals["ANGEL_PUBLIC_IP"] = os.environ.get("ANGEL_PUBLIC_IP", "")
    if os.path.exists(SECRETS_FILE):
        with open(SECRETS_FILE, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                if k in vals and not vals[k]:
                    vals[k] = v.strip().strip('"').strip("'")
    return vals


def totp(secret, at=None, digits=6, step=30):
    """RFC 6238 TOTP (SHA-1), the same code an authenticator app shows."""
    key = base64.b32decode(secret.replace(" ", "").upper() + "=" * (-len(secret.replace(" ", "")) % 8))
    counter = int((at if at is not None else time.time()) // step)
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    code = (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def mac():
    n = uuid.getnode()
    return ":".join("%02x" % ((n >> s) & 0xFF) for s in range(40, -1, -8))


# ---------------------------------------------------------------- HTTP client

class Client:
    def __init__(self, secrets=None, opener=None):
        self.s = secrets if secrets is not None else load_secrets()
        self.open = opener or urllib.request.urlopen
        self.last = 0.0
        sess = read_json(SESSION_FILE, {}) or {}
        today = ist(now_utc()).date().isoformat()
        self.jwt = sess.get("jwt") if sess.get("date") == today else None
        self.feed = sess.get("feed") if sess.get("date") == today else None

    def headers(self, auth=True):
        h = {"Content-Type": "application/json", "Accept": "application/json", "X-UserType": "USER",
             "X-SourceID": "WEB", "X-ClientLocalIP": local_ip(),
             "X-ClientPublicIP": self.s.get("ANGEL_PUBLIC_IP") or "", "X-MACAddress": mac(),
             "X-PrivateKey": self.s.get("ANGEL_API_KEY", "")}
        if auth:
            if not self.jwt:
                raise AngelError("not logged in today: run `angel.py login`")
            h["Authorization"] = "Bearer " + self.jwt
        return h

    def call(self, method, path, body=None, auth=True):
        wait = GAP - (time.time() - self.last)
        if wait > 0:
            time.sleep(wait)
        self.last = time.time()
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(BASE + path, data=data, method=method, headers=self.headers(auth))
        try:
            with self.open(req, timeout=20) as r:
                raw = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            audit("http_error", path=path, code=e.code)
            if e.code == 403:
                raise AngelError("HTTP 403 from Angel One: rate limit hit, or the request did not come from "
                                 "your registered static IP. Stop and check `angel.py doctor`.")
            raise AngelError("HTTP %s from Angel One for %s" % (e.code, path))
        except (urllib.error.URLError, socket.timeout) as e:
            audit("net_error", path=path, error=str(e)[:120])
            raise AngelError("network error for %s: %s" % (path, str(e)[:120]))
        try:
            doc = json.loads(raw)
        except ValueError:
            audit("bad_json", path=path)
            raise AngelError("Angel One sent a reply that is not JSON for %s" % path)
        audit("call", path=path, body=body, status=doc.get("status"), errorcode=doc.get("errorcode"),
              message=doc.get("message"))
        if doc.get("status") is not True and doc.get("success") is not True:
            code = doc.get("errorcode") or ""
            if code in ("AG8001", "AG8002", "AG8003"):
                raise AngelError("session token invalid or expired (%s): run `angel.py login`" % code)
            raise AngelError("Angel One refused %s: %s %s" % (path, code, doc.get("message", "")))
        return doc.get("data")

    # ---- session
    def login(self):
        missing = [k for k in KEYS if not self.s.get(k)]
        if missing:
            raise AngelError("missing keys: %s. Put them in %s yourself (never in the chat)."
                             % (", ".join(missing), SECRETS_FILE))
        body = {"clientcode": self.s["ANGEL_CLIENT_CODE"], "password": self.s["ANGEL_MPIN"],
                "totp": totp(self.s["ANGEL_TOTP_SECRET"])}
        d = self.call("POST", "/rest/auth/angelbroking/user/v1/loginByPassword", body, auth=False)
        self.jwt, self.feed = d.get("jwtToken"), d.get("feedToken")
        os.makedirs(HOME, exist_ok=True)
        write_json(SESSION_FILE, {"date": ist(now_utc()).date().isoformat(), "jwt": self.jwt,
                                  "feed": self.feed})
        try:
            os.chmod(SESSION_FILE, 0o600)
        except OSError:
            pass
        return True

    def logout(self):
        try:
            self.call("POST", "/rest/secure/angelbroking/user/v1/logout",
                      {"clientcode": self.s.get("ANGEL_CLIENT_CODE", "")})
        finally:
            if os.path.exists(SESSION_FILE):
                os.remove(SESSION_FILE)

    # ---- read-only
    def profile(self):
        return self.call("GET", "/rest/secure/angelbroking/user/v1/getProfile")

    def funds(self):
        return self.call("GET", "/rest/secure/angelbroking/user/v1/getRMS")

    def orders(self):
        return self.call("GET", "/rest/secure/angelbroking/order/v1/getOrderBook") or []

    def trades(self):
        return self.call("GET", "/rest/secure/angelbroking/order/v1/getTradeBook") or []

    def positions(self):
        return self.call("GET", "/rest/secure/angelbroking/order/v1/getPosition") or []

    def holdings(self):
        return self.call("GET", "/rest/secure/angelbroking/portfolio/v1/getAllHolding")

    def order_details(self, unique_id):
        return self.call("GET", "/rest/secure/angelbroking/order/v1/details/" + unique_id)

    def quote(self, mode, tokens_by_exchange):
        d = self.call("POST", "/rest/secure/angelbroking/market/v1/quote/",
                      {"mode": mode, "exchangeTokens": tokens_by_exchange})
        return (d or {}).get("fetched", [])

    def candles(self, exchange, token, interval, frm, to):
        return self.call("POST", "/rest/secure/angelbroking/historical/v1/getCandleData",
                         {"exchange": exchange, "symboltoken": token, "interval": interval,
                          "fromdate": frm, "todate": to}) or []

    def margin(self, positions):
        return self.call("POST", "/rest/secure/angelbroking/margin/v1/batch", {"positions": positions})

    def charges(self, orders):
        return self.call("POST", "/rest/secure/angelbroking/brokerage/v1/estimateCharges", {"orders": orders})

    def cautionary(self):
        return self.call("GET", "/rest/secure/angelbroking/securities/v1/cautionaryScrips") or []

    # ---- order writes (only reached through the gates below)
    def place(self, body):
        return self.call("POST", "/rest/secure/angelbroking/order/v1/placeOrder", body)

    def modify(self, body):
        return self.call("POST", "/rest/secure/angelbroking/order/v1/modifyOrder", body)

    def cancel(self, variety, order_id):
        return self.call("POST", "/rest/secure/angelbroking/order/v1/cancelOrder",
                         {"variety": variety, "orderid": order_id})

    def convert(self, body):
        return self.call("POST", "/rest/secure/angelbroking/order/v1/convertPosition", body)


# ---------------------------------------------------------------- instruments

def refresh_scrips(opener=None, force=False):
    """Download the scrip master once a day; keep only NSE, BSE, NFO and BFO rows."""
    today = ist(now_utc()).date().isoformat()
    cur = read_json(SCRIPS)
    if cur and cur.get("date") == today and not force:
        return cur["rows"]
    req = urllib.request.Request(SCRIP_URL, headers={"User-Agent": "Mozilla/5.0 (compatible; trader-skill/1.0)"})
    with (opener or urllib.request.urlopen)(req, timeout=120) as r:
        rows = json.loads(r.read().decode("utf-8"))
    keep = [{k: x.get(k) for k in ("token", "symbol", "name", "expiry", "strike", "lotsize",
                                    "instrumenttype", "exch_seg", "tick_size", "freeze_qty",
                                    "is_cas_enabled")}
            for x in rows if x.get("exch_seg") in SEGMENTS]
    write_json(SCRIPS, {"date": today, "rows": keep})
    return keep


def instrument(rows, symbol, exchange):
    """One scrip-master row. NSE cash symbols resolve with or without -EQ."""
    sym, ex = symbol.upper(), exchange.upper()
    want = [sym] if ex != "NSE" or sym.endswith("-EQ") else [sym + "-EQ", sym]
    for w in want:
        for r in rows:
            if r.get("exch_seg") == ex and str(r.get("symbol", "")).upper() == w:
                return info(r)
    raise AngelError("no %s instrument named %s in the scrip master (try `angel.py search`)" % (ex, sym))


def info(r):
    f = lambda k: float(r.get(k) or 0)  # noqa: E731
    return {"token": str(r["token"]), "tradingsymbol": r["symbol"], "name": r.get("name", ""),
            "exchange": r["exch_seg"], "type": r.get("instrumenttype", ""), "expiry": r.get("expiry", ""),
            "strike": f("strike") / 100.0, "lot": max(1, int(f("lotsize"))), "tick": f("tick_size") / 100.0,
            "freeze": int(f("freeze_qty")), "cas": bool(r.get("is_cas_enabled"))}


def underlying(rows, inst):
    """The spot instrument for an F&O row: the index (AMXIDX) or the NSE/BSE cash stock."""
    cash = "BSE" if inst["exchange"] == "BFO" else "NSE"
    name = inst["name"].upper()
    for r in rows:
        if r.get("exch_seg") == cash and str(r.get("name", "")).upper() == name and \
                (r.get("instrumenttype") == "AMXIDX" or str(r.get("symbol", "")).upper() in (name + "-EQ", name)):
            return info(r)
    return None


def expiry_date(text):
    try:
        return datetime.datetime.strptime(text, "%d%b%Y").date()
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- config and gates

def cfg_limits(cfg):
    a = dict(cfg.get("angel") or {})
    lim = {}
    for k, hard in HARD.items():
        v = a.get(k)
        lim[k] = min(float(v), hard) if v is not None else hard
    lim["max_orders_per_day"] = int(lim["max_orders_per_day"])
    lim["allow_fno"] = bool(a.get("allow_fno", True))
    lim["allow_option_selling"] = bool(a.get("allow_option_selling", False))
    lim["allow_futures"] = bool(a.get("allow_futures", False))
    return lim


def is_live(cfg):
    return (cfg.get("paper") is False and str(cfg.get("broker", "")).lower() == "angelone"
            and os.environ.get("ANGEL_LIVE") == "1")


def placed_today(state, today):
    return [r for r in state.get("orders", []) if ticket.rec_day(r) == today and r.get("status") == "placed"]


def window_problem(now_ist, kind, inst):
    """Exchange-time reasons to refuse an order now (IST)."""
    d, t = now_ist.date(), now_ist.time()
    extra = read_json(os.path.join("trader", "nse_holidays.json"), {}) or {}
    if d.weekday() >= 5 or d.isoformat() in HOLIDAYS or d.isoformat() in extra:
        return "the market is closed today"
    if not (OPEN <= t < CLOSE):
        return "the market is closed now (%s IST)" % t.strftime("%H:%M")
    if CAS_START <= t < CAS_END:
        return "Angel One rejects API orders from 15:15 to 15:20 (closing auction)"
    if kind == "entry" and inst["exchange"] in FNO and expiry_date(inst["expiry"]) == d \
            and t >= NO_ENTRY_AFTER_EXPIRY_DAY:
        return "no new F&O entries after 14:30 on expiry day"
    return None


def fno_problem(order, inst, kind, lim, spot, long_opts):
    if inst["exchange"] not in FNO:
        return None
    if not lim["allow_fno"]:
        return "F&O is switched off (angel.allow_fno)"
    qty = int(float(order["qty"]))
    if qty % inst["lot"]:
        return "quantity %d is not a multiple of the lot size %d" % (qty, inst["lot"])
    if inst["freeze"] and qty > inst["freeze"]:
        return "quantity %d is over the exchange freeze limit %d" % (qty, inst["freeze"])
    if inst["type"].startswith("FUT") and kind == "entry" and not lim["allow_futures"]:
        return "futures entries are switched off (angel.allow_futures)"
    if inst["type"].startswith("OPT"):
        if str(order.get("type", "limit")).lower() != "limit":
            return "options use LIMIT orders only"
        if kind == "entry" and order["side"] == "sell":
            if not lim["allow_option_selling"]:
                return "option selling is switched off (angel.allow_option_selling)"
            hedge = long_opts.get((inst["name"], inst["expiry"], inst["tradingsymbol"][-2:]), 0)
            if hedge < qty:
                return "a sold option needs a bought option of the same underlying, expiry and type " \
                       "(have %d, need %d)" % (hedge, qty)
        if kind == "entry" and spot:
            dist = abs(inst["strike"] - spot) / spot * 100
            if dist > lim["max_strike_distance_pct"]:
                return "strike %g is %.1f%% from spot %.2f (max %.1f%%)" % (
                    inst["strike"], dist, spot, lim["max_strike_distance_pct"])
    return None


def price_problem(order, inst, ltp, quote, lim):
    typ = str(order.get("type", "limit")).lower()
    if typ not in TYPES:
        return "order type %s is not supported" % typ
    if typ == "market":
        return None
    px = float(order.get("limit_price") or 0)
    if px <= 0:
        return "a limit order needs limit_price"
    if not on_tick(px, inst["tick"]):
        return "limit price %.2f is not a multiple of the tick %.2f" % (px, inst["tick"])
    if ltp and abs(px - ltp) / ltp * 100 > lim["price_band_pct"]:
        return "limit price %.2f is more than %.1f%% from the last price %.2f" % (px, lim["price_band_pct"], ltp)
    lo, hi = _f(quote.get("lowerCircuit")), _f(quote.get("upperCircuit"))
    if lo and hi and not (lo <= px <= hi):
        return "limit price %.2f is outside the circuit band %.2f-%.2f" % (px, lo, hi)
    return None


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def build_body(order, inst, fp):
    typ = str(order.get("type", "limit")).lower()
    product = PRODUCTS.get(str(order.get("product", "intraday")).lower())
    if not product:
        raise AngelError("product must be one of: %s" % ", ".join(PRODUCTS))
    body = {"variety": "STOPLOSS" if typ.startswith("stop") else "NORMAL",
            "tradingsymbol": inst["tradingsymbol"], "symboltoken": inst["token"],
            "transactiontype": order["side"].upper(), "exchange": inst["exchange"],
            "ordertype": TYPES[typ], "producttype": product,
            "duration": "IOC" if str(order.get("time_in_force", "day")).lower() == "ioc" else "DAY",
            "price": "%.2f" % float(order.get("limit_price") or 0) if typ != "market" else "0",
            "triggerprice": "%.2f" % float(order.get("stop_price") or 0) if typ.startswith("stop") else "0",
            "quantity": str(int(float(order["qty"]))), "squareoff": "0", "stoploss": "0",
            "ordertag": fp}
    return body


# ---------------------------------------------------------------- paper broker

def paper_place(body, ltp):
    book = read_json(PAPER, {"orders": []})
    oid = "PAPER-%d" % (len(book["orders"]) + 1)
    px = float(body["price"]) if body["ordertype"] != "MARKET" else ltp
    filled = body["variety"] == "NORMAL" and px
    rec = dict(body, orderid=oid, uniqueorderid=oid, status="complete" if filled else "open",
               averageprice=px if filled else 0, filledshares=body["quantity"] if filled else "0",
               at=now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"))
    book["orders"].append(rec)
    write_json(PAPER, book)
    return rec


# ---------------------------------------------------------------- commands

def _ctx(a):
    orders_doc = read_json(a.orders, {}) or {}
    orders = orders_doc.get("orders", [])
    cfg = read_json(a.config, {}) or {}
    risk = read_json(a.risk, None)
    state = ticket.load_state(a.state)
    now = ticket.parse_now(a.now) if a.now else now_utc()
    today = ist(now).date().isoformat()
    return orders, cfg, risk, state, now, today


def _client(a):
    return getattr(a, "_client", None) or Client()


def _live_quote(cl, inst, cfg):
    """(ltp, full quote dict). Paper mode without a session falls back to trader/prices.json."""
    try:
        q = cl.quote("FULL", {inst["exchange"]: [inst["token"]]})
        if q:
            return float(q[0].get("ltp") or 0), q[0]
    except AngelError:
        if is_live(cfg):
            raise
    p = (read_json(os.path.join("trader", "prices.json"), {}) or {}).get("prices", {})
    v = p.get(inst["tradingsymbol"].replace("-EQ", "")) or p.get(inst["tradingsymbol"])
    if v:
        return float(v), {}
    raise AngelError("no fresh price for %s: log in, or run `alerts.py quote SYMBOL --write`" % inst["tradingsymbol"])


def cmd_place(a):
    orders, cfg, risk, state, now, today = _ctx(a)
    if os.path.exists(STOP_FILE):
        raise AngelError("trader/STOP exists: all orders are stopped. The user removes that file to resume.")
    if not (1 <= a.index <= len(orders)):
        raise AngelError("no order %d in %s" % (a.index, a.orders))
    order = orders[a.index - 1]
    fp = ticket.fingerprint(order)
    # Gate 1: trader-risk PASS for this exact order today.
    rv, why = ticket.risk_verdict(risk, fp, today)
    if rv is None or rv.get("verdict") != "PASS":
        raise AngelError("gate 1 failed: %s" % (why or "trader-risk did not PASS this order"))
    # Gate 2: the user's yes, recorded by ticket.py approve, still the latest record.
    rec = ticket.latest(state, fp, today)
    if not rec or rec.get("status") != "approved":
        raise AngelError("gate 2 failed: no yes from the user is recorded for order %d today "
                         "(ticket.py approve), or it was already sent" % a.index)
    kind = rec.get("kind") or ticket.kind_of(order, rv)
    lim = cfg_limits(cfg)
    if kind == "entry" and len(placed_today(state, today)) >= lim["max_orders_per_day"]:
        raise AngelError("hard limit: %d orders already placed today" % lim["max_orders_per_day"])
    cl = _client(a)
    rows = refresh_scrips(getattr(a, "_opener", None))
    inst = instrument(rows, order["symbol"], order.get("exchange", "NSE"))
    problem = window_problem(ist(now), kind, inst)
    ltp, quote = _live_quote(cl, inst, cfg)
    value = int(float(order["qty"])) * (float(order.get("limit_price") or 0) or ltp)
    if not problem and kind == "entry" and value > lim["max_order_value"]:
        problem = "hard limit: order value Rs %.0f is over Rs %.0f" % (value, lim["max_order_value"])
    if not problem:
        problem = price_problem(order, inst, ltp, quote, lim)
    if not problem and inst["exchange"] in FNO:
        spot = None
        u = underlying(rows, inst)
        if u and kind == "entry":
            spot, _ = _live_quote(cl, u, cfg)
        problem = fno_problem(order, inst, kind, lim, spot, _long_options(cl, cfg, rows))
    if not problem and kind == "entry" and inst["exchange"] in ("NSE", "BSE") and is_live(cfg):
        if any(str(c.get("token")) == inst["token"] for c in cl.cautionary()):
            problem = "the exchange lists %s as a cautionary (ASM/GSM) scrip" % inst["tradingsymbol"]
    if problem:
        audit("blocked", index=a.index, fingerprint=fp, reason=problem)
        raise AngelError("not sent: " + problem)
    body = build_body(order, inst, fp)
    live = is_live(cfg)
    if live:
        dupe = [o for o in cl.orders() if o.get("ordertag") == fp]
        if dupe:
            raise AngelError("not sent: the order book already has an order tagged %s (id %s)"
                             % (fp, dupe[0].get("orderid")))
        if order.get("modify_of"):
            res = cl.modify(dict(body, orderid=str(order["modify_of"])))
        else:
            res = cl.place(body)
        if not res or not res.get("orderid"):
            raise AngelError("Angel One did not return an order id; check `angel.py orders` before any retry")
        det = {}
        try:
            det = cl.order_details(res.get("uniqueorderid", "")) or {}
        except AngelError:
            pass
        oid, status = res["orderid"], det.get("orderstatus") or det.get("status") or "sent"
        avg, filled = _f(det.get("averageprice")), int(_f(det.get("filledshares")) or 0)
    else:
        det = paper_place(body, ltp)
        oid, status, avg, filled = det["orderid"], det["status"], det["averageprice"], int(det["filledshares"])
    new = {"at": ticket.local_iso(now), "date": today,
           "index": a.index, "fingerprint": fp, "symbol": rec["symbol"], "side": rec["side"],
           "plain": rec.get("plain"), "status": "placed", "broker_order_id": oid,
           "broker": "angelone" if live else "paper", "note": "broker status: %s" % status}
    for k in ("qty", "kind", "max_loss", "stop"):
        if rec.get(k) is not None:
            new[k] = rec[k]
    state.setdefault("orders", []).append(new)
    ticket.write_json(a.state, state)
    audit("placed", index=a.index, fingerprint=fp, live=live, orderid=oid, status=status)
    print("%s order %d sent: %s. Order id %s, status %s." % ("LIVE" if live else "PAPER", a.index,
                                                            rec.get("plain"), oid, status))
    if filled and avg:
        # The order is already at the broker: a local bookkeeping error must not hide that.
        try:
            ticket.log_fill(a.state, now, today, rec["symbol"], rec["side"], filled, avg)
            ticket.apply_fill(a.portfolio, cfg, rec["symbol"], rec["side"], filled, avg, today)
            print("Filled %d at %.2f. Recorded in %s." % (filled, avg, a.portfolio))
        except Exception as e:  # noqa: BLE001
            audit("fill_record_error", orderid=oid, error=str(e)[:200])
            print("WARNING: filled %d at %.2f, but the local record failed (%s). Record it with "
                  "`ticket.py fill`." % (filled, avg, e))
        if kind == "entry" and order.get("stop_loss_stop_price"):
            print("Next: `angel.py protect --index %d` places the stop-loss at %s." % (
                a.index, order["stop_loss_stop_price"]))
    else:
        print("Not filled yet. Check `angel.py orders`. When it fills, run `angel.py protect --index %d`."
              % a.index)
    return 0


def _long_options(cl, cfg, rows):
    """{(name, expiry, CE|PE): long qty} from broker positions (live) or the paper portfolio."""
    out = {}
    pos = []
    if is_live(cfg):
        pos = [(p.get("tradingsymbol"), p.get("exchange"), int(_f(p.get("netqty")) or 0)) for p in cl.positions()]
    else:
        pf = read_json(os.path.join("trader", "portfolio.json"), {}) or {}
        for p in pf.get("positions") or []:
            pos.append((p.get("ticker"), "NFO", int(_f(p.get("shares")) or 0)))
    for sym, ex, q in pos:
        if q <= 0 or not str(sym).endswith(("CE", "PE")):
            continue
        for r in rows:
            if r.get("symbol") == sym and r.get("exch_seg") in FNO:
                key = (r.get("name"), r.get("expiry"), sym[-2:])
                out[key] = out.get(key, 0) + q
                break
    return out


def cmd_protect(a):
    """After an entry fills: one stop-loss order to exit at the plan's stop. Same yes covers it."""
    orders, cfg, risk, state, now, today = _ctx(a)
    order = orders[a.index - 1]
    fp = ticket.fingerprint(order)
    placed = [r for r in state.get("orders", []) if r.get("fingerprint") == fp and r.get("status") == "placed"
              and ticket.rec_day(r) == today]
    if not placed:
        raise AngelError("order %d was not placed today; nothing to protect" % a.index)
    if any(r.get("status") == "protected" and r.get("fingerprint") == fp for r in state.get("orders", [])):
        raise AngelError("order %d already has its stop-loss" % a.index)
    stop = _f(order.get("stop_loss_stop_price") or (order.get("plan") or {}).get("stop"))
    if not stop:
        raise AngelError("order %d has no stop price" % a.index)
    cl = _client(a)
    inst = instrument(refresh_scrips(getattr(a, "_opener", None)), order["symbol"], order.get("exchange", "NSE"))
    exit_side = "sell" if order["side"] == "buy" else "buy"
    buf = max(inst["tick"], stop * 0.01)
    limit = tick_round(stop - buf if exit_side == "sell" else stop + buf, inst["tick"], exit_side)
    trig = tick_round(stop, inst["tick"], "sell" if exit_side == "buy" else "buy")
    stop_order = {"symbol": order["symbol"], "exchange": inst["exchange"], "side": exit_side,
                  "qty": order["qty"], "type": "stop_limit", "stop_price": trig, "limit_price": limit,
                  "product": order.get("product", "intraday")}
    body = build_body(stop_order, inst, ("S" + fp)[:16])
    if is_live(cfg):
        res = cl.place(body)
        oid = (res or {}).get("orderid")
    else:
        oid = paper_place(body, 0)["orderid"]
    state["orders"].append({"at": ticket.local_iso(now), "date": today, "index": a.index, "fingerprint": fp,
                            "symbol": order["symbol"].upper(), "side": exit_side, "status": "protected",
                            "broker_order_id": oid, "stop": trig, "limit": limit})
    ticket.write_json(a.state, state)
    audit("protect", index=a.index, orderid=oid, trigger=trig, limit=limit)
    print("Stop-loss placed for order %d: %s %s at trigger %.2f, limit %.2f. Order id %s."
          % (a.index, exit_side.upper(), order["qty"], trig, limit, oid))
    return 0


def cmd_modify(a):
    """Only changes that lower risk: fewer shares, a tighter stop, or a new exit price."""
    cfg = read_json(a.config, {}) or {}
    cl = _client(a)
    if not is_live(cfg):
        raise AngelError("modify works on live Angel One orders only (paper orders fill at once)")
    cur = next((o for o in cl.orders() if str(o.get("orderid")) == str(a.order_id)), None)
    if not cur:
        raise AngelError("no order %s in today's order book" % a.order_id)
    if str(cur.get("orderstatus", cur.get("status", ""))).lower() not in ("open", "trigger pending", "open pending"):
        raise AngelError("order %s is %s; only open orders can change" % (a.order_id, cur.get("orderstatus")))
    side = str(cur.get("transactiontype", "")).lower()
    qty = int(_f(cur.get("quantity")) or 0)
    new_qty = int(a.qty) if a.qty else qty
    if new_qty > qty:
        raise AngelError("more quantity adds risk: write a new order and send it through check.py and a yes")
    stop_order = str(cur.get("variety")) == "STOPLOSS"
    old_trig = _f(cur.get("triggerprice")) or 0
    new_trig = float(a.trigger) if a.trigger else old_trig
    if stop_order and a.trigger:
        tighter = new_trig >= old_trig if side == "sell" else new_trig <= old_trig
        if not tighter:
            raise AngelError("a looser stop adds risk: send it as a new order through check.py and a yes")
    if not stop_order and a.price and side == "buy":
        raise AngelError("a new entry price changes the risk: send it as a new order with modify_of=%s "
                         "through check.py and a yes" % a.order_id)
    body = {"variety": cur.get("variety"), "orderid": str(a.order_id), "ordertype": cur.get("ordertype"),
            "producttype": cur.get("producttype"), "duration": cur.get("duration", "DAY"),
            "price": "%.2f" % float(a.price if a.price else _f(cur.get("price")) or 0),
            "triggerprice": "%.2f" % new_trig, "quantity": str(new_qty),
            "tradingsymbol": cur.get("tradingsymbol"), "symboltoken": cur.get("symboltoken"),
            "exchange": cur.get("exchange")}
    cl.modify(body)
    audit("modify", orderid=a.order_id, body=body)
    print("Order %s changed: qty %d, price %s, trigger %s." % (a.order_id, new_qty, body["price"],
                                                              body["triggerprice"]))
    return 0


def cmd_convert(a):
    cfg = read_json(a.config, {}) or {}
    reply = " ".join((a.reply or "").lower().split())
    if not re.search(r"\byes\b", reply) or a.symbol.lower() not in reply:
        raise AngelError("convert needs the user's own yes that names the symbol, e.g. --reply \"yes convert %s\""
                         % a.symbol.upper())
    if not is_live(cfg):
        print("PAPER: would convert %s %s %s from %s to %s." % (a.side, a.qty, a.symbol, a.frm, a.to))
        return 0
    cl = _client(a)
    inst = instrument(refresh_scrips(getattr(a, "_opener", None)), a.symbol, a.exchange)
    if a.to.upper() == "DELIVERY" and a.side == "buy":
        ltp, _ = _live_quote(cl, inst, cfg)
        cash = _f((cl.funds() or {}).get("availablecash")) or 0
        if cash < ltp * int(a.qty):
            raise AngelError("not enough cash to hold %s %s overnight (need about Rs %.0f, have Rs %.0f)"
                             % (a.qty, a.symbol, ltp * int(a.qty), cash))
    body = {"exchange": inst["exchange"], "symboltoken": inst["token"], "oldproducttype": a.frm.upper(),
            "newproducttype": a.to.upper(), "tradingsymbol": inst["tradingsymbol"],
            "transactiontype": a.side.upper(), "quantity": int(a.qty), "type": "DAY"}
    cl.convert(body)
    audit("convert", body=body, reply=a.reply)
    print("Converted %s %s %s from %s to %s." % (a.side, a.qty, a.symbol, a.frm.upper(), a.to.upper()))
    return 0


def cmd_cancel(a):
    cl = _client(a)
    cur = next((o for o in cl.orders() if str(o.get("orderid")) == str(a.order_id)), None)
    if not cur:
        raise AngelError("no order %s in today's order book" % a.order_id)
    cl.cancel(cur.get("variety", "NORMAL"), str(a.order_id))
    audit("cancel", orderid=a.order_id)
    print("Cancel sent for order %s." % a.order_id)
    return 0


def cmd_kill(a):
    """Cancel every open order. With --flatten, also exit every open intraday position."""
    os.makedirs("trader", exist_ok=True)
    with open(STOP_FILE, "w", encoding="utf-8") as fh:
        fh.write("Stopped at %s by angel.py kill. Delete this file to allow orders again.\n" % now_utc())
    cfg = read_json(a.config, {}) or {}
    print("Wrote trader/STOP: no new orders until the user deletes it.")
    if not is_live(cfg):
        print("PAPER mode: nothing to cancel at the broker.")
        return 0
    cl = _client(a)
    n = 0
    for o in cl.orders():
        if str(o.get("orderstatus", "")).lower() in ("open", "trigger pending", "open pending"):
            try:
                cl.cancel(o.get("variety", "NORMAL"), str(o.get("orderid")))
                n += 1
            except AngelError as e:
                print("Could not cancel %s: %s" % (o.get("orderid"), e))
    print("Cancel sent for %d open orders." % n)
    if a.flatten:
        rows = refresh_scrips(getattr(a, "_opener", None))
        for p in cl.positions():
            q = int(_f(p.get("netqty")) or 0)
            if q == 0 or str(p.get("producttype")).upper() != "INTRADAY":
                continue
            inst = instrument(rows, p["tradingsymbol"], p["exchange"])
            ltp, _ = _live_quote(cl, inst, cfg)
            side = "sell" if q > 0 else "buy"
            px = tick_round(ltp * (0.99 if side == "sell" else 1.01), inst["tick"], side)
            body = build_body({"side": side, "qty": abs(q), "type": "limit", "limit_price": px,
                               "product": "intraday"}, inst, "KILL")
            try:
                res = cl.place(body)
                print("Exit sent: %s %d %s at %.2f (order %s)." % (side.upper(), abs(q), p["tradingsymbol"],
                                                                 px, (res or {}).get("orderid")))
            except AngelError as e:
                print("Exit FAILED for %s: %s. Exit it in the Angel One app now." % (p["tradingsymbol"], e))
    audit("kill", cancelled=n, flatten=bool(a.flatten))
    return 0


def cmd_doctor(a):
    s = load_secrets()
    cfg = read_json(a.config, {}) or {}
    print("Secrets file: %s (%s). The script reads it; agents never open it." % (
        SECRETS_FILE, "found" if os.path.exists(SECRETS_FILE) else "missing"))
    for k in KEYS + ("ANGEL_PUBLIC_IP",):
        print("  %-18s %s" % (k, "present" if s.get(k) else "missing"))
    print("Mode: %s." % ("LIVE" if is_live(cfg) else "PAPER (live needs config paper=false, broker=angelone, "
                                                   "and ANGEL_LIVE=1)"))
    print("Limits: %s." % json.dumps(cfg_limits(cfg)))
    print("Kill switch trader/STOP: %s." % ("ON" if os.path.exists(STOP_FILE) else "off"))
    sess = read_json(SESSION_FILE, {}) or {}
    print("Session: %s." % ("logged in today" if sess.get("date") == ist(now_utc()).date().isoformat()
                            else "not logged in"))
    print("Static IP: from 1 April 2026 Angel One accepts API orders only from the static IP registered "
          "on your SmartAPI app. Set ANGEL_PUBLIC_IP to that IP.")
    return 0


def cmd_simple(a):
    cl = _client(a)
    if a.cmd == "login":
        cl.login()
        print("Logged in. The session lasts until midnight IST.")
        return 0
    if a.cmd == "logout":
        cl.logout()
        print("Logged out.")
        return 0
    data = getattr(cl, a.cmd)()
    print(json.dumps(mask(data), indent=2))
    return 0


def cmd_search(a):
    rows = refresh_scrips(getattr(a, "_opener", None))
    q = a.query.upper()
    hits = []
    for r in rows:
        if r.get("exch_seg") != a.exchange.upper() or q not in str(r.get("symbol", "")).upper():
            continue
        i = info(r)
        if a.expiry and i["expiry"].upper() != a.expiry.upper():
            continue
        if a.strike and abs(i["strike"] - float(a.strike)) > 1e-6:
            continue
        if a.type and not i["tradingsymbol"].upper().endswith(a.type.upper()):
            continue
        hits.append(i)
    for i in hits[:a.limit]:
        print("%-28s %-4s token %-8s lot %-5d tick %.2f %s %s" % (
            i["tradingsymbol"], i["exchange"], i["token"], i["lot"], i["tick"], i["expiry"],
            ("strike %g" % i["strike"]) if i["strike"] > 0 else ""))
    print("%d match(es)%s." % (len(hits), "" if len(hits) <= a.limit else ", first %d shown" % a.limit))
    return 0


def cmd_ltp(a):
    cl = _client(a)
    rows = refresh_scrips(getattr(a, "_opener", None))
    insts = [instrument(rows, s, a.exchange) for s in a.symbols]
    by_ex = {}
    for i in insts:
        by_ex.setdefault(i["exchange"], []).append(i["token"])
    got = {str(q.get("symbolToken")): q for q in cl.quote("LTP", by_ex)}
    quotes = {}
    for s, i in zip(a.symbols, insts):
        q = got.get(i["token"])
        if q:
            quotes[s.upper()] = {"price": float(q["ltp"]), "prev_close": _f(q.get("close")),
                                 "time": ist(now_utc()).strftime("%H:%M IST"), "source": "angelone"}
            print("%-14s %10.2f" % (s.upper(), float(q["ltp"])))
    if a.write and quotes:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                        "trader-alerts"))
        prices_path = os.path.join("trader", "prices.json")
        doc = read_json(prices_path, {}) or {}
        prices, detail = dict(doc.get("prices", {})), dict(doc.get("detail", {}))
        stamp = now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
        for s, q in quotes.items():
            prices[s] = q["price"]
            detail[s] = dict(q, fetched=stamp)
        write_json(prices_path, {"as_of": stamp, "source": "angelone", "prices": prices, "detail": detail})
        print("Saved to %s." % prices_path)
    return 0


def cmd_candles(a):
    cl = _client(a)
    inst = instrument(refresh_scrips(getattr(a, "_opener", None)), a.symbol, a.exchange)
    rows = cl.candles(inst["exchange"], inst["token"], a.interval, getattr(a, "from"), a.to)
    out = [{"t": r[0], "o": r[1], "h": r[2], "l": r[3], "c": r[4], "v": r[5]} for r in rows]
    if a.out:
        write_json(a.out, {"symbol": a.symbol.upper(), "exchange": inst["exchange"], "interval": a.interval,
                           "candles": out})
        print("%d candles saved to %s." % (len(out), a.out))
    else:
        print(json.dumps(out[-a.last:], indent=1))
    return 0


def _order_rows(a, need):
    orders, cfg, risk, state, now, today = _ctx(a)
    order = orders[a.index - 1]
    inst = instrument(refresh_scrips(getattr(a, "_opener", None)), order["symbol"], order.get("exchange", "NSE"))
    return order, inst, _client(a), cfg


def cmd_margin(a):
    order, inst, cl, cfg = _order_rows(a, "margin")
    pos = [{"exchange": inst["exchange"], "qty": int(float(order["qty"])),
            "price": float(order.get("limit_price") or 0), "productType": PRODUCTS.get(
                str(order.get("product", "intraday")).lower(), "INTRADAY"),
            "token": inst["token"], "tradeType": order["side"].upper()}]
    d = cl.margin(pos) or {}
    print("Margin needed: Rs %s." % d.get("totalMarginRequired"))
    return 0


def cmd_charges(a):
    order, inst, cl, cfg = _order_rows(a, "charges")
    body = [{"product_type": PRODUCTS.get(str(order.get("product", "intraday")).lower(), "INTRADAY"),
             "transaction_type": order["side"].upper(), "quantity": str(int(float(order["qty"]))),
             "price": str(order.get("limit_price") or 0), "exchange": inst["exchange"],
             "symbol_name": inst["name"], "token": inst["token"]}]
    print(json.dumps(cl.charges(body), indent=2))
    return 0


def parser():
    ap = argparse.ArgumentParser(description="Angel One SmartAPI client (trader-broker).")
    ap.add_argument("--orders", default="trader/orders.json")
    ap.add_argument("--config", default="trader/config.json")
    ap.add_argument("--risk", default="trader/state/risk.json")
    ap.add_argument("--state", default="trader/state/broker.json")
    ap.add_argument("--portfolio", default="trader/portfolio.json")
    ap.add_argument("--now", help='pin the clock: "2026-11-11 10:15" (IST)')
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("doctor", "login", "logout", "profile", "funds", "orders", "trades", "positions", "holdings"):
        sub.add_parser(c)
    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--exchange", default="NSE")
    p.add_argument("--expiry")
    p.add_argument("--strike")
    p.add_argument("--type", choices=["CE", "PE", "FUT"])
    p.add_argument("--limit", type=int, default=25)
    p = sub.add_parser("ltp")
    p.add_argument("symbols", nargs="+")
    p.add_argument("--exchange", default="NSE")
    p.add_argument("--write", action="store_true")
    p = sub.add_parser("candles")
    p.add_argument("symbol")
    p.add_argument("--exchange", default="NSE")
    p.add_argument("--interval", default="FIVE_MINUTE",
                   choices=["ONE_MINUTE", "THREE_MINUTE", "FIVE_MINUTE", "TEN_MINUTE", "FIFTEEN_MINUTE",
                            "THIRTY_MINUTE", "ONE_HOUR", "ONE_DAY"])
    p.add_argument("--from", required=True)
    p.add_argument("--to", required=True)
    p.add_argument("--out")
    p.add_argument("--last", type=int, default=20)
    for c in ("margin", "charges", "place", "protect"):
        p = sub.add_parser(c)
        p.add_argument("--index", type=int, required=True)
    p = sub.add_parser("modify")
    p.add_argument("--order-id", required=True)
    p.add_argument("--price")
    p.add_argument("--trigger")
    p.add_argument("--qty")
    p = sub.add_parser("cancel")
    p.add_argument("--order-id", required=True)
    p = sub.add_parser("convert")
    p.add_argument("--symbol", required=True)
    p.add_argument("--exchange", default="NSE")
    p.add_argument("--side", choices=["buy", "sell"], required=True)
    p.add_argument("--qty", required=True)
    p.add_argument("--from", dest="frm", required=True)
    p.add_argument("--to", required=True)
    p.add_argument("--reply", required=True, help="the user's own words, quoted")
    p = sub.add_parser("kill")
    p.add_argument("--flatten", action="store_true")
    return ap


CMDS = {"doctor": cmd_doctor, "search": cmd_search, "ltp": cmd_ltp, "candles": cmd_candles,
        "margin": cmd_margin, "charges": cmd_charges, "place": cmd_place, "protect": cmd_protect,
        "modify": cmd_modify, "convert": cmd_convert, "cancel": cmd_cancel, "kill": cmd_kill}


def main(argv=None):
    a = parser().parse_args(argv)
    try:
        return CMDS.get(a.cmd, cmd_simple)(a)
    except AngelError as e:
        print("STOP: %s" % e)
        return 2


if __name__ == "__main__":
    import sys as _sys
    if hasattr(_sys.stdout, "reconfigure"):
        _sys.stdout.reconfigure(errors="replace")
    sys.exit(main())
