"""Tests for order_builder module."""

import pytest
from order_builder import (
    build_entry_condition,
    build_order_proposal,
    build_revalidation_advisory,
)

ORDER_FIELDS = {
    "symbol", "exchange", "product", "side", "qty", "type", "time_in_force",
    "limit_price", "order_class", "stop_loss_stop_price", "take_profit_limit_price",
}


class TestBuildOrderProposal:
    def test_orders_json_shape_and_string_values(self):
        order = build_order_proposal(
            symbol="SBIN",
            qty=20,
            entry_limit=800.0,
            stop_loss=790.0,
            take_profit=820.0,
        )
        assert set(order) == ORDER_FIELDS
        assert all(isinstance(v, str) for v in order.values())
        assert order["symbol"] == "SBIN"
        assert order["exchange"] == "NSE"
        assert order["product"] == "delivery"
        assert order["side"] == "buy"
        assert order["qty"] == "20"
        assert order["type"] == "limit"
        assert order["time_in_force"] == "day"
        assert order["limit_price"] == "800.00"
        assert order["order_class"] == "bracket"
        assert order["stop_loss_stop_price"] == "790.00"
        assert order["take_profit_limit_price"] == "820.00"

    def test_intraday_product(self):
        order = build_order_proposal("SBIN", 5, 800.0, 790.0, 820.0, product="intraday")
        assert order["product"] == "intraday"

    def test_bad_product_raises(self):
        with pytest.raises(ValueError, match="product"):
            build_order_proposal("SBIN", 5, 800.0, 790.0, 820.0, product="carryforward")

    def test_no_alpaca_fields(self):
        order = build_order_proposal("SBIN", 5, 800.0, 790.0, 820.0)
        for key in ("take_profit", "stop_loss", "stop_price", "execution_mode", "notional"):
            assert key not in order

    def test_qty_zero_raises(self):
        with pytest.raises(ValueError, match="qty must be positive"):
            build_order_proposal("X", 0, 102.0, 95.0, 110.0)

    def test_stop_too_close_to_entry_raises(self):
        with pytest.raises(ValueError, match="stop_loss.*at least"):
            build_order_proposal("X", 10, 102.0, 102.0, 110.0)

    def test_stop_one_tick_below_is_allowed(self):
        order = build_order_proposal("X", 10, 102.0, 101.95, 110.0)
        assert order["stop_loss_stop_price"] == "101.95"

    def test_take_profit_below_entry_raises(self):
        with pytest.raises(ValueError, match="take_profit.*must be above"):
            build_order_proposal("X", 10, 102.0, 95.0, 101.0)


class TestBuildRevalidationAdvisory:
    def test_advisory_structure(self):
        advisory = build_revalidation_advisory(
            symbol="ANET",
            pivot=141.77,
            current_price=145.07,
            worst_entry=144.60,
        )
        assert advisory["symbol"] == "ANET"
        assert advisory["plan_type"] == "late_breakout_revalidation"
        assert advisory["next_action"].startswith("revalidate")
        assert advisory["pivot"] == 141.77
        assert advisory["current_price"] == 145.07
        assert advisory["max_entry_price"] == 144.60

    def test_no_order_fields(self):
        advisory = build_revalidation_advisory(
            symbol="X",
            pivot=100.0,
            current_price=103.0,
            worst_entry=102.0,
        )
        assert "qty" not in advisory
        assert "type" not in advisory
        assert "order_class" not in advisory


class TestBuildEntryCondition:
    def test_machine_readable_format(self):
        cond = build_entry_condition(pivot=319.52)
        assert cond["bar_interval"] == "5min"
        assert cond["trigger"]["field"] == "close"
        assert cond["trigger"]["op"] == ">"
        assert cond["trigger"]["value"] == 319.52
        assert len(cond["checks"]) == 3

    def test_custom_thresholds(self):
        cond = build_entry_condition(
            pivot=100.0,
            close_loc_min=0.70,
            rvol_threshold=2.0,
            max_chase_pct=1.5,
        )
        assert cond["checks"][0]["value"] == 0.70
        assert cond["checks"][1]["value"] == 2.0
        assert cond["checks"][2]["value"] == 1.5
