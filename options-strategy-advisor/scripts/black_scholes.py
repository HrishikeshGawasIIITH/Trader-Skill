#!/usr/bin/env python3
"""
Black-Scholes options pricing for NSE options (stdlib only).

- European call and put prices and all Greeks (Delta, Gamma, Theta, Vega, Rho)
- Historical volatility from daily closes
- NSE F&O lot sizes from fo_mktlots.csv
- Spot and history through india_client (Yahoo data, no keys)

Notes for India:
- NSE index options (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY) are European-style,
  so Black-Scholes applies directly.
- Default risk-free rate is 6.5% (India 91-day T-bill). Pass your own with r=...
- Prices are in rupees. Lot sizes change. Read the current file each time.

Usage:
    from black_scholes import OptionPricer

    pricer = OptionPricer(S=24500, K=24600, T=14/365, r=0.065, sigma=0.14)
    pricer.call_price()
    pricer.call_delta()

CLI:
    python3 black_scholes.py --symbol NIFTY --spot 24500 --strike 24600 --days 14 --iv 14
    python3 black_scholes.py --symbol RELIANCE --strike 1500 --days 21 --live
"""

import argparse
import csv
import io
import math
import statistics
import sys
import urllib.request

DEFAULT_RISK_FREE_RATE = 0.065  # India 91-day T-bill, user can override
TRADING_DAYS = 252
LOT_SIZE_URL = "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"
)
INDEX_OPTION_SYMBOLS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}
INDEX_SPOT_SYMBOLS = {  # Yahoo symbols for index spot
    "NIFTY": "^NSEI",
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
}


def _cdf(x):
    """Standard normal CDF."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _pdf(x):
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


class OptionPricer:
    """Black-Scholes option pricer with Greeks calculation"""

    def __init__(self, S, K, T, r=DEFAULT_RISK_FREE_RATE, sigma=0.20, q=0):
        """
        Parameters:
        -----------
        S : float
            Spot price (Rs)
        K : float
            Strike price (Rs)
        T : float
            Time to expiration in years (e.g., 30/365 for 30 days)
        r : float
            Risk-free interest rate (annual, default 0.065 for 6.5%)
        sigma : float
            Volatility (annual, e.g., 0.14 for 14%)
        q : float, optional
            Continuous dividend yield (annual, default 0)
        """
        self.S = S
        self.K = K
        self.T = T
        self.r = r
        self.sigma = sigma
        self.q = q

        if S <= 0:
            raise ValueError("Stock price must be positive")
        if K <= 0:
            raise ValueError("Strike price must be positive")
        if T <= 0:
            raise ValueError("Time to expiration must be positive")
        if sigma <= 0:
            raise ValueError("Volatility must be positive")

    def _d1(self):
        numerator = math.log(self.S / self.K) + (self.r - self.q + 0.5 * self.sigma**2) * self.T
        return numerator / (self.sigma * math.sqrt(self.T))

    def _d2(self):
        return self._d1() - self.sigma * math.sqrt(self.T)

    # ---- Pricing -----------------------------------------------------------

    def call_price(self):
        """European call price"""
        d1, d2 = self._d1(), self._d2()
        price = self.S * math.exp(-self.q * self.T) * _cdf(d1) - self.K * math.exp(
            -self.r * self.T
        ) * _cdf(d2)
        return max(0, price)

    def put_price(self):
        """European put price"""
        d1, d2 = self._d1(), self._d2()
        price = self.K * math.exp(-self.r * self.T) * _cdf(-d2) - self.S * math.exp(
            -self.q * self.T
        ) * _cdf(-d1)
        return max(0, price)

    # ---- Greeks: first order -------------------------------------------------

    def call_delta(self):
        """Change in option price per Rs 1 change in spot (0 to 1)"""
        return math.exp(-self.q * self.T) * _cdf(self._d1())

    def put_delta(self):
        """Change in option price per Rs 1 change in spot (-1 to 0)"""
        return math.exp(-self.q * self.T) * (_cdf(self._d1()) - 1)

    def vega(self):
        """Change in option price per 1% change in volatility (same for calls and puts)"""
        d1 = self._d1()
        v = self.S * math.exp(-self.q * self.T) * _pdf(d1) * math.sqrt(self.T)
        return v / 100

    def call_theta(self):
        """Change in call price per calendar day (usually negative)"""
        d1, d2 = self._d1(), self._d2()
        term1 = (
            -self.S
            * _pdf(d1)
            * self.sigma
            * math.exp(-self.q * self.T)
            / (2 * math.sqrt(self.T))
        )
        term2 = -self.r * self.K * math.exp(-self.r * self.T) * _cdf(d2)
        term3 = self.q * self.S * _cdf(d1) * math.exp(-self.q * self.T)
        return (term1 + term2 + term3) / 365

    def put_theta(self):
        """Change in put price per calendar day"""
        d1, d2 = self._d1(), self._d2()
        term1 = (
            -self.S
            * _pdf(d1)
            * self.sigma
            * math.exp(-self.q * self.T)
            / (2 * math.sqrt(self.T))
        )
        term2 = self.r * self.K * math.exp(-self.r * self.T) * _cdf(-d2)
        term3 = -self.q * self.S * _cdf(-d1) * math.exp(-self.q * self.T)
        return (term1 + term2 + term3) / 365

    def call_rho(self):
        """Change in call price per 1% change in interest rate"""
        rho = self.K * self.T * math.exp(-self.r * self.T) * _cdf(self._d2())
        return rho / 100

    def put_rho(self):
        """Change in put price per 1% change in interest rate"""
        rho = -self.K * self.T * math.exp(-self.r * self.T) * _cdf(-self._d2())
        return rho / 100

    # ---- Greeks: second order ------------------------------------------------

    def gamma(self):
        """Change in delta per Rs 1 change in spot (same for calls and puts)"""
        d1 = self._d1()
        return (math.exp(-self.q * self.T) * _pdf(d1)) / (
            self.S * self.sigma * math.sqrt(self.T)
        )

    # ---- Utility -------------------------------------------------------------

    def intrinsic_value(self, option_type="call"):
        if option_type.lower() == "call":
            return max(0, self.S - self.K)
        return max(0, self.K - self.S)

    def time_value(self, option_type="call"):
        price = self.call_price() if option_type.lower() == "call" else self.put_price()
        return price - self.intrinsic_value(option_type)

    def moneyness(self):
        """'ATM', 'ITM (Call) / OTM (Put)' or 'OTM (Call) / ITM (Put)'"""
        ratio = self.S / self.K
        if abs(ratio - 1.0) < 0.02:
            return "ATM"
        elif ratio > 1.0:
            return "ITM (Call) / OTM (Put)"
        return "OTM (Call) / ITM (Put)"

    def get_all_greeks(self, option_type="call"):
        """All Greeks for a call or put as a dict"""
        if option_type.lower() == "call":
            return {
                "price": self.call_price(),
                "delta": self.call_delta(),
                "gamma": self.gamma(),
                "theta": self.call_theta(),
                "vega": self.vega(),
                "rho": self.call_rho(),
                "intrinsic_value": self.intrinsic_value("call"),
                "time_value": self.time_value("call"),
            }
        return {
            "price": self.put_price(),
            "delta": self.put_delta(),
            "gamma": self.gamma(),
            "theta": self.put_theta(),
            "vega": self.vega(),
            "rho": self.put_rho(),
            "intrinsic_value": self.intrinsic_value("put"),
            "time_value": self.time_value("put"),
        }


# =============================================================================
# Historical volatility
# =============================================================================


def calculate_historical_volatility(prices, window=30):
    """Annualized historical volatility from daily closes (oldest first)."""
    prices = list(prices)
    if len(prices) < window + 1:
        raise ValueError(f"Need at least {window + 1} price points")
    log_returns = [math.log(prices[i + 1] / prices[i]) for i in range(len(prices) - 1)]
    recent = log_returns[-window:]
    return statistics.pstdev(recent) * math.sqrt(TRADING_DAYS)


# =============================================================================
# Data through india_client (no keys)
# =============================================================================


def _client(client=None):
    if client is not None:
        return client
    from india_client import FMPClient

    return FMPClient(quiet=True)


def yahoo_spot_symbol(symbol):
    """NIFTY -> ^NSEI, BANKNIFTY -> ^NSEBANK, RELIANCE -> RELIANCE (client adds .NS)."""
    return INDEX_SPOT_SYMBOLS.get(symbol.upper(), symbol)


def fetch_historical_prices_for_hv(symbol, client=None, days=90):
    """Closing prices, oldest first, for a historical volatility calculation."""
    try:
        data = _client(client).get_historical_prices(yahoo_spot_symbol(symbol), days=days)
    except Exception as exc:
        print(f"Error fetching prices for {symbol}: {exc}", file=sys.stderr)
        return None
    hist = (data or {}).get("historical") or []
    closes = [h["close"] for h in hist[:days] if h.get("close")]
    if not closes:
        print(f"Error fetching prices for {symbol}: no data", file=sys.stderr)
        return None
    return closes[::-1]


def get_current_stock_price(symbol, client=None):
    """Latest spot price (Rs) or None."""
    try:
        quotes = _client(client).get_quote(yahoo_spot_symbol(symbol))
    except Exception:
        quotes = None
    if quotes and quotes[0].get("price") is not None:
        return quotes[0]["price"]
    print(f"Error fetching current price for {symbol}", file=sys.stderr)
    return None


def get_dividend_yield(symbol, client=None):
    """No free dividend-yield source for NSE. Returns 0. Pass q=... yourself if you need it."""
    return 0.0


# =============================================================================
# NSE F&O lot sizes
# =============================================================================


def parse_lot_sizes(csv_text):
    """Parse fo_mktlots.csv -> {SYMBOL: {"name", "lot", "months": {"NOV-26": 65, ...}}}.

    "lot" is the size for the nearest listed expiry month.
    """
    out = {}
    reader = csv.reader(io.StringIO((csv_text or "").lstrip("﻿")))
    months = []
    for row in reader:
        cells = [c.strip() for c in row]
        if len(cells) < 3:
            continue
        if cells[1].upper() == "SYMBOL":  # header rows (index block and stock block)
            months = cells[2:]
            continue
        symbol = cells[1]
        if not symbol or not months:
            continue
        lots = {}
        for label, val in zip(months, cells[2:]):
            if label and val.isdigit():
                lots[label] = int(val)
        if not lots:
            continue
        out[symbol.upper()] = {"name": cells[0], "lot": next(iter(lots.values())), "months": lots}
    return out


def fetch_lot_sizes(url=LOT_SIZE_URL, timeout=30, opener=None):
    """Download and parse the NSE lot-size file. Returns {} on failure."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        opener = opener or urllib.request.build_opener()
        body = opener.open(req, timeout=timeout).read().decode("utf-8-sig", errors="replace")
    except Exception as exc:
        print(f"Error fetching lot sizes: {exc}", file=sys.stderr)
        return {}
    return parse_lot_sizes(body)


def lot_size(symbol, lots=None):
    """Lot size for an F&O symbol (nearest expiry) or None when not listed."""
    lots = lots if lots is not None else fetch_lot_sizes()
    entry = lots.get(symbol.upper())
    return entry["lot"] if entry else None


# =============================================================================
# CLI
# =============================================================================


def build_report(symbol, spot, strike, days, iv, rate, dividend, lots=None):
    """Plain-text pricing report for one strike (call and put)."""
    pricer = OptionPricer(S=spot, K=strike, T=days / 365, r=rate, sigma=iv, q=dividend)
    lot = lot_size(symbol, lots) if symbol else None
    style = "European (index option)" if symbol and symbol.upper() in INDEX_OPTION_SYMBOLS else "check the contract style"
    lines = [
        f"Option pricing {symbol or ''}".strip(),
        f"  Spot Rs {spot:,.2f}, strike Rs {strike:,.2f}, {days} days, IV {iv * 100:.1f}%, rate {rate * 100:.2f}%, dividend {dividend * 100:.1f}%",
        f"  Exercise style: {style}. Moneyness: {pricer.moneyness()}",
        f"  Lot size: {lot if lot else 'not found'}",
    ]
    for kind in ("call", "put"):
        g = pricer.get_all_greeks(kind)
        lines.append(
            f"  {kind.upper():4} price Rs {g['price']:,.2f} | delta {g['delta']:+.4f} | gamma {g['gamma']:.6f} | "
            f"theta Rs {g['theta']:+.2f}/day | vega Rs {g['vega']:.2f}/1% IV | rho Rs {g['rho']:+.2f}/1% rate"
        )
        if lot:
            lines.append(f"       one lot ({lot}): premium Rs {g['price'] * lot:,.0f}, theta Rs {g['theta'] * lot:+,.0f}/day")
    return "\n".join(lines)


def main(argv=None, client=None, lots=None):
    p = argparse.ArgumentParser(description="Black-Scholes pricing for NSE options")
    p.add_argument("--symbol", default=None, help="NIFTY, BANKNIFTY, RELIANCE ...")
    p.add_argument("--spot", type=float, default=None, help="Spot price in Rs")
    p.add_argument("--strike", type=float, required=True)
    p.add_argument("--days", type=int, required=True, help="Calendar days to expiry")
    p.add_argument("--iv", type=float, default=None, help="Implied volatility in percent (e.g. 14)")
    p.add_argument("--rate", type=float, default=DEFAULT_RISK_FREE_RATE * 100, help="Risk-free rate in percent (default 6.5)")
    p.add_argument("--dividend", type=float, default=0.0, help="Dividend yield in percent")
    p.add_argument("--live", action="store_true", help="Fetch spot and 30-day historical volatility")
    args = p.parse_args(argv)

    spot, iv = args.spot, (args.iv / 100 if args.iv else None)
    if args.live:
        if not args.symbol:
            p.error("--live needs --symbol")
        spot = spot or get_current_stock_price(args.symbol, client)
        if iv is None:
            closes = fetch_historical_prices_for_hv(args.symbol, client, days=90)
            if closes and len(closes) > 31:
                iv = calculate_historical_volatility(closes, 30)
                print(f"Using 30-day historical volatility {iv * 100:.1f}% (no IV given)", file=sys.stderr)
    if spot is None or iv is None:
        p.error("need --spot and --iv (or --live with --symbol)")
    print(build_report(args.symbol, spot, args.strike, args.days, iv, args.rate / 100, args.dividend / 100, lots))
    return 0


if __name__ == "__main__":
    import sys as _sys
    if hasattr(_sys.stdout, "reconfigure"):
        _sys.stdout.reconfigure(errors="replace")
    raise SystemExit(main())
