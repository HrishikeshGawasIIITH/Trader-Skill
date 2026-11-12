"""Order proposal builder for the breakout trade planner.

Builds one bracket order proposal per Pre-breakout candidate in the shape of
trader/orders.json (every value a string). The planner never places orders.
trader-risk checks each proposal and trader-broker places it.

Breakout candidates get revalidation advisories only (no order proposal).
"""

from __future__ import annotations

TICK = 0.05  # NSE cash-market tick size in rupees
VALID_PRODUCTS = ("intraday", "delivery")


def _price(value: float) -> str:
    return f"{value:.2f}"


def build_order_proposal(
    symbol: str,
    qty: int,
    entry_limit: float,
    stop_loss: float,
    take_profit: float,
    product: str = "delivery",
    time_in_force: str = "day",
) -> dict:
    """Build a bracket limit order proposal in trader/orders.json shape.

    The entry is a limit at the worst-case entry (the highest price you accept).
    Send it only after the live confirmation in the entry condition passes.

    Raises:
        ValueError: On invalid inputs.
    """
    if product not in VALID_PRODUCTS:
        raise ValueError(f"product must be one of {VALID_PRODUCTS}, got {product!r}")
    if qty <= 0:
        raise ValueError(f"qty must be positive, got {qty}")
    if (entry_limit - stop_loss) < TICK - 1e-9:
        raise ValueError(
            f"stop_loss ({stop_loss}) must be at least Rs {TICK} below entry_limit ({entry_limit})"
        )
    if take_profit <= entry_limit:
        raise ValueError(f"take_profit ({take_profit}) must be above entry_limit ({entry_limit})")

    return {
        "symbol": str(symbol),
        "exchange": "NSE",
        "product": product,
        "side": "buy",
        "qty": str(int(qty)),
        "type": "limit",
        "time_in_force": time_in_force,
        "limit_price": _price(entry_limit),
        "order_class": "bracket",
        "stop_loss_stop_price": _price(stop_loss),
        "take_profit_limit_price": _price(take_profit),
    }


def build_revalidation_advisory(
    symbol: str,
    pivot: float,
    current_price: float,
    worst_entry: float,
) -> dict:
    """Build an advisory for Breakout-state candidates (no order proposal).

    These candidates already crossed the pivot and need live revalidation
    before any order can be proposed.
    """
    return {
        "symbol": symbol,
        "plan_type": "late_breakout_revalidation",
        "next_action": "revalidate live price/5min confirmation before any order",
        "pivot": pivot,
        "current_price": current_price,
        "max_entry_price": worst_entry,
    }


def build_entry_condition(
    pivot: float,
    close_loc_min: float = 0.60,
    rvol_threshold: float = 1.5,
    max_chase_pct: float = 2.0,
) -> dict:
    """Build a machine-readable confirmation to pass before the order is proposed."""
    return {
        "bar_interval": "5min",
        "trigger": {"field": "close", "op": ">", "value": pivot},
        "checks": [
            {"field": "close_loc", "op": ">=", "value": close_loc_min},
            {"field": "tod_rvol", "op": ">=", "value": rvol_threshold},
            {"field": "price_vs_pivot_pct", "op": "<=", "value": max_chase_pct},
        ],
    }
