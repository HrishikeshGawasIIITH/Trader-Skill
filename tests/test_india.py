"""India rules: trader-risk F&O and product checks, and the Angel One client gates (no network)."""

import datetime
import json
import os
import shutil
import tempfile
import unittest

from _load import load

check = load("trader-risk", "check")
angel = load("trader-broker", "angel")
ticket = angel.ticket

NOW = check.parse_now("2026-11-11 10:30")          # Wednesday, IST
RULES = {"budget": 100000, "max_order_inr": 25000, "max_loss_per_trade_inr": 500,
         "max_daily_loss_inr": 2000, "min_reward_risk": 1.0, "allow_short": False}


def sbin(**kw):
    o = {"symbol": "SBIN", "exchange": "NSE", "product": "intraday", "side": "buy", "qty": "20",
         "type": "limit", "time_in_force": "day", "limit_price": "800.00",
         "order_class": "bracket", "stop_loss_stop_price": "790.00", "take_profit_limit_price": "820.00"}
    o.update(kw)
    return o


def nifty_ce(**kw):
    o = {"symbol": "NIFTY17NOV2624000CE", "exchange": "NFO", "product": "intraday", "side": "buy",
         "qty": "75", "type": "limit", "time_in_force": "day", "limit_price": "100.00",
         "order_class": "bracket", "stop_loss_stop_price": "95.00", "take_profit_limit_price": "110.00"}
    o.update(kw)
    return o


class RiskIndia(unittest.TestCase):
    def one(self, o, state=None, **over):
        c = dict(RULES)
        c.update(over)
        return check.check([o], c, now=NOW, state=state)["results"][0]

    def test_inr_keys_are_read(self):
        r = self.one(sbin(qty="60"))          # 60 x 10 = 600 at the stop, over 500
        self.assertEqual(r["verdict"], "BLOCK")
        self.assertIn("max loss", " ".join(r["reasons"]))

    def test_a_cash_order_passes(self):
        r = self.one(sbin())
        self.assertEqual(r["verdict"], "PASS", r["reasons"])

    def test_product_and_exchange_rules(self):
        self.assertIn("exchange must be", " ".join(self.one(sbin(exchange="NYSE"))["reasons"]))
        self.assertIn("carryforward is for F&O", " ".join(self.one(sbin(product="carryforward"))["reasons"]))
        self.assertIn("not delivery", " ".join(self.one(nifty_ce(product="delivery"))["reasons"]))

    def test_option_buy_passes_and_warns(self):
        r = self.one(nifty_ce())
        self.assertEqual(r["verdict"], "PASS", r["reasons"])
        self.assertIn("100%", " ".join(r["warnings"]))

    def test_fno_symbol_shape_and_switch(self):
        self.assertIn("not an F&O trading symbol", " ".join(self.one(nifty_ce(symbol="NIFTY"))["reasons"]))
        self.assertIn("F&O is off", " ".join(self.one(nifty_ce(), allow_fno=False)["reasons"]))

    def test_option_writing_is_a_short(self):
        r = self.one(nifty_ce(side="sell", stop_loss_stop_price="105.00", take_profit_limit_price="90.00"))
        self.assertIn("short", " ".join(r["reasons"]))

    def test_losing_streak_breaker(self):
        fills = []
        for px in (95, 96, 97):
            fills += [{"status": "filled", "symbol": "SBIN", "side": "buy", "qty": "10", "price": 100},
                      {"status": "filled", "symbol": "SBIN", "side": "sell", "qty": "10", "price": px}]
        self.assertEqual(check.losing_streak({"orders": fills}), 3)
        r = self.one(sbin(), state={"orders": fills})
        self.assertIn("circuit breaker", " ".join(r["reasons"]))
        fills.append({"status": "filled", "symbol": "TCS", "side": "buy", "qty": "1", "price": 10})
        fills.append({"status": "filled", "symbol": "TCS", "side": "sell", "qty": "1", "price": 12})
        self.assertEqual(check.losing_streak({"orders": fills}), 0)

    def test_modify_of_needs_a_placed_order(self):
        self.assertIn("modify_of", " ".join(self.one(sbin(modify_of="123"))["reasons"]))
        placed = {"orders": [{"date": "2026-11-11", "status": "placed", "symbol": "SBIN", "side": "buy",
                              "kind": "entry", "max_loss": 200, "broker_order_id": "123"}]}
        r = self.one(sbin(modify_of="123", limit_price="801.00"), state=placed)
        self.assertEqual(r["verdict"], "PASS", r["reasons"])


ROWS = [
    {"token": "3045", "symbol": "SBIN-EQ", "name": "SBIN", "expiry": "", "strike": "-1.000000", "lotsize": "1",
     "instrumenttype": "", "exch_seg": "NSE", "tick_size": "5.000000", "freeze_qty": "0", "is_cas_enabled": True},
    {"token": "99926000", "symbol": "Nifty 50", "name": "NIFTY", "expiry": "", "strike": "0", "lotsize": "1",
     "instrumenttype": "AMXIDX", "exch_seg": "NSE", "tick_size": "0", "freeze_qty": "0", "is_cas_enabled": False},
    {"token": "40000", "symbol": "NIFTY17NOV2624000CE", "name": "NIFTY", "expiry": "17NOV2026",
     "strike": "2400000.000000", "lotsize": "75", "instrumenttype": "OPTIDX", "exch_seg": "NFO",
     "tick_size": "5.000000", "freeze_qty": "1800", "is_cas_enabled": False},
    {"token": "40001", "symbol": "NIFTY17NOV2630000CE", "name": "NIFTY", "expiry": "17NOV2026",
     "strike": "3000000.000000", "lotsize": "75", "instrumenttype": "OPTIDX", "exch_seg": "NFO",
     "tick_size": "5.000000", "freeze_qty": "1800", "is_cas_enabled": False},
]


class FakeClient:
    def __init__(self, ltp):
        self.ltp, self.sent = ltp, []

    def quote(self, mode, tokens):
        tok = list(tokens.values())[0][0]
        return [{"ltp": self.ltp.get(tok, 0), "symbolToken": tok, "lowerCircuit": "1", "upperCircuit": "99999"}]

    def orders(self):
        return []

    def positions(self):
        return []

    def cautionary(self):
        return []

    def place(self, body):
        self.sent.append(body)
        return {"orderid": "A1", "uniqueorderid": "U1"}

    def order_details(self, uid):
        return {"orderstatus": "complete", "averageprice": "800", "filledshares": "20"}


class AngelGates(unittest.TestCase):
    def setUp(self):
        self.old = os.getcwd()
        self.tmp = tempfile.mkdtemp()
        os.chdir(self.tmp)
        os.makedirs("trader/state")
        os.makedirs("trader/cache")
        today = "2026-11-11"
        with open("trader/cache/scrips.json", "w") as fh:
            json.dump({"date": today, "rows": ROWS}, fh)
        self.real_refresh = angel.refresh_scrips
        angel.refresh_scrips = lambda *a, **k: ROWS
        self.cfg = {"paper": True, "budget": 100000, "angel": {}}
        os.environ.pop("ANGEL_LIVE", None)

    def tearDown(self):
        angel.refresh_scrips = self.real_refresh
        os.chdir(self.old)
        shutil.rmtree(self.tmp, ignore_errors=True)

    day = "2026-11-11"

    def write(self, orders, risk=True, approve=True):
        with open("trader/orders.json", "w") as fh:
            json.dump({"orders": orders}, fh)
        with open("trader/config.json", "w") as fh:
            json.dump(self.cfg, fh)
        fps = [ticket.fingerprint(o) for o in orders]
        if risk:
            with open("trader/state/risk.json", "w") as fh:
                json.dump({"date": self.day, "results": [
                    {"fingerprint": f, "verdict": "PASS", "kind": "entry"} for f in fps]}, fh)
        if approve:
            with open("trader/state/broker.json", "w") as fh:
                json.dump({"orders": [{"date": self.day, "fingerprint": f, "status": "approved",
                                       "symbol": o["symbol"], "side": o["side"], "qty": o["qty"],
                                       "kind": "entry", "plain": "test"} for f, o in zip(fps, orders)]}, fh)

    def run_place(self, ltp, now="2026-11-11 10:30"):
        a = angel.parser().parse_args(["--now", now, "place", "--index", "1"])
        a._client = FakeClient(ltp)
        try:
            return angel.CMDS["place"](a), a._client
        except angel.AngelError as e:
            return str(e), a._client

    def test_totp_matches_rfc6238(self):
        self.assertEqual(angel.totp("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", at=59), "287082")

    def test_mask_hides_secrets(self):
        m = angel.mask({"password": "1234", "totp": "1", "data": {"jwtToken": "x", "ltp": 5}})
        self.assertEqual(m, {"password": "***", "totp": "***", "data": {"jwtToken": "***", "ltp": 5}})

    def test_ticks(self):
        self.assertEqual(angel.tick_round(100.03, 0.05, "buy"), 100.0)
        self.assertEqual(angel.tick_round(100.03, 0.05, "sell"), 100.05)
        self.assertTrue(angel.on_tick(100.05, 0.05))
        self.assertFalse(angel.on_tick(100.03, 0.05))

    def test_paper_place_passes_all_gates(self):
        self.write([sbin()])
        res, cl = self.run_place({"3045": 800.0})
        self.assertEqual(res, 0)
        self.assertEqual(cl.sent, [])          # paper: nothing reached the broker
        state = json.load(open("trader/state/broker.json"))
        self.assertIn("placed", [r["status"] for r in state["orders"]])

    def test_gate1_needs_risk_pass(self):
        self.write([sbin()], risk=False)
        res, _ = self.run_place({"3045": 800.0})
        self.assertIn("gate 1", res)

    def test_gate2_needs_the_users_yes(self):
        self.write([sbin()], approve=False)
        res, _ = self.run_place({"3045": 800.0})
        self.assertIn("gate 2", res)

    def test_stop_file_blocks_everything(self):
        self.write([sbin()])
        open("trader/STOP", "w").close()
        res, _ = self.run_place({"3045": 800.0})
        self.assertIn("trader/STOP", res)

    def test_hard_value_cap_and_price_band(self):
        self.write([sbin(qty="40")])                       # 40 x 800 = 32,000
        self.assertIn("hard limit", self.run_place({"3045": 800.0})[0])
        self.write([sbin()])
        self.assertIn("from the last price", self.run_place({"3045": 750.0})[0])
        self.write([sbin(limit_price="800.03")])
        self.assertIn("tick", self.run_place({"3045": 800.0})[0])

    def test_config_cannot_raise_a_hard_limit(self):
        self.assertEqual(angel.cfg_limits({"angel": {"max_order_value": 10 ** 9}})["max_order_value"],
                         angel.HARD["max_order_value"])
        self.assertEqual(angel.cfg_limits({"angel": {"max_order_value": 5000}})["max_order_value"], 5000)

    def test_closing_auction_and_market_hours(self):
        self.write([sbin()])
        self.assertIn("15:15 to 15:20", self.run_place({"3045": 800.0}, now="2026-11-11 15:16")[0])
        self.assertIn("closed", self.run_place({"3045": 800.0}, now="2026-11-11 16:00")[0])
        self.day = "2026-11-24"
        self.write([sbin()])
        self.assertIn("closed", self.run_place({"3045": 800.0}, now="2026-11-24 10:30")[0])

    def test_fno_lot_and_strike_distance(self):
        self.write([nifty_ce(qty="50")])
        self.assertIn("lot size 75", self.run_place({"40000": 100.0, "99926000": 24050.0})[0])
        self.write([nifty_ce(qty="75")])
        self.assertEqual(self.run_place({"40000": 100.0, "99926000": 24050.0})[0], 0)
        far = nifty_ce(symbol="NIFTY17NOV2630000CE")
        self.write([far])
        self.assertIn("from spot", self.run_place({"40001": 100.0, "99926000": 24050.0})[0])

    def test_option_selling_off_and_needs_hedge(self):
        o = nifty_ce(side="sell")
        self.write([o])
        self.assertIn("option selling is switched off", self.run_place({"40000": 100.0, "99926000": 24050.0})[0])
        self.cfg["angel"] = {"allow_option_selling": True}
        self.write([o])
        self.assertIn("needs a bought option", self.run_place({"40000": 100.0, "99926000": 24050.0})[0])

    def test_expiry_day_cutoff(self):
        self.day = "2026-11-17"
        self.write([nifty_ce()])
        self.assertIn("expiry day", self.run_place({"40000": 100.0, "99926000": 24050.0},
                                                   now="2026-11-17 14:31")[0])

    def test_live_needs_three_switches(self):
        self.assertFalse(angel.is_live({"paper": False, "broker": "angelone"}))
        os.environ["ANGEL_LIVE"] = "1"
        try:
            self.assertTrue(angel.is_live({"paper": False, "broker": "angelone"}))
            self.assertFalse(angel.is_live({"paper": True, "broker": "angelone"}))
        finally:
            os.environ.pop("ANGEL_LIVE")

    def test_live_place_sends_tagged_order(self):
        self.cfg = {"paper": False, "broker": "angelone", "budget": 100000}
        self.write([sbin()])
        os.environ["ANGEL_LIVE"] = "1"
        try:
            res, cl = self.run_place({"3045": 800.0})
        finally:
            os.environ.pop("ANGEL_LIVE")
        self.assertEqual(res, 0)
        body = cl.sent[0]
        self.assertEqual((body["tradingsymbol"], body["ordertype"], body["producttype"], body["quantity"]),
                         ("SBIN-EQ", "LIMIT", "INTRADAY", "20"))
        self.assertEqual(body["ordertag"], ticket.fingerprint(sbin()))


if __name__ == "__main__":
    unittest.main()
