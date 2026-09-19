#!/usr/bin/env python3
"""
Test Suite: Institutional Pro Desk Trader Trailing Stop Loss (R-Multiple Ratchet)
Verifies:
1. Trade entry with initial SL and defined risk.
2. Initial risk protected before +1.0R expansion.
3. +1.0R expansion moves SL to Breakeven (Risk = 0).
4. +1.5R expansion activates Trailing Ratchet: locks +0.5R.
5. +2.0R expansion steps Trailed SL up to +1.0R (locks +1.0R profit).
6. Severe retracement hits Trailed SL: closes in guaranteed green profit (TRAILING_SL_HIT).
7. Symmetrical execution for SELL positions.
"""
import os
import sys
import unittest
from datetime import datetime, timezone, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.execution.kite_trader import KiteTrader
from src.indicator.models import Candle

IST = timezone(timedelta(hours=5, minutes=30))

def make_candle(ts, o, h, l, c):
    return {
        "timestamp": ts,
        "open": float(o),
        "high": float(h),
        "low": float(l),
        "close": float(c),
        "volume": 1000
    }

def test_buy_trailing_ratchet():
    print("\n======================================================================")
    print("--- TEST 1: BUY Trailing Stop Loss Ratchet (+1.0R BE -> +0.5R -> +1.0R) ---")
    print("======================================================================")

    config = {
        "trade_management": {
            "mode": "ict_pro",
            "enable_breakeven_at_1r": True,
            "breakeven_trigger_r": 1.0,
            "enable_trailing_sl": True,
            "trailing_activation_r": 1.5,
            "trailing_distance_r": 1.0,
            "trailing_step_r": 0.5,
            "enable_near_tp_lock": True,
            "near_tp_threshold_pct": 85.0
        }
    }

    os.environ["PAPER_MODE"] = "true"
    trader = KiteTrader(config)
    trader.stop_monitoring()
    ts = int(datetime(2026, 9, 21, 9, 30, tzinfo=IST).timestamp())

    # 1. Place BUY Trade: Spot 25000, SL 24960 (Risk = 40 pts), TP 25120 (3R)
    trade_id = trader.place_order(
        signal={
            "signal": "BUY",
            "entry_price": 25000.0,
            "sl_price": 24960.0,
            "tp_price": 25120.0,
            "model": "Unicorn Model (Breaker + IFVG)"
        },
        instrument_name="NIFTY 50",
        lots=1
    )
    assert trade_id is not None, "Order should be placed"
    trade = trader.get_open_trades().get(trade_id)
    assert trade["current_sl"] == 24960.0
    print(f"✅ Trade entered: Entry 25000, Initial SL {trade['current_sl']}, Risk = 40 pts")

    # 2. Candle 1: High reaches 25030 (+0.75R) -> SL remains 24960
    trader.check_trades_with_candle("NIFTY 50", make_candle(ts + 300, 25000, 25030, 24990, 25020))
    trade = trader.get_open_trades().get(trade_id)
    assert trade["current_sl"] == 24960.0
    assert not trade.get("breakeven_moved")
    print(f"✅ +0.75R expansion: SL unchanged at {trade['current_sl']} (Healthy breathing room)")

    # 3. Candle 2: High reaches 25045 (+1.1R) -> BE triggered! SL = 25000.0
    evs = trader.check_trades_with_candle("NIFTY 50", make_candle(ts + 600, 25020, 25045, 25010, 25040))
    trade = trader.get_open_trades().get(trade_id)
    assert trade["breakeven_moved"] is True
    assert trade["current_sl"] == 25000.0
    print(f"✅ +1.1R expansion: Breakeven triggered! SL moved to {trade['current_sl']} (Risk = ₹0)")

    # 4. Candle 3: High reaches 25070 (+1.75R) -> Trailing Ratchet locks +0.5R profit!
    # raw_lock = 1.75 - 1.0 = 0.75 -> floor(0.75/0.5)*0.5 = 0.5R -> SL = 25000 + 0.5*40 = 25020.0
    evs = trader.check_trades_with_candle("NIFTY 50", make_candle(ts + 900, 25040, 25070, 25035, 25065))
    trade = trader.get_open_trades().get(trade_id)
    assert trade["trailed_r"] == 0.5
    assert trade["current_sl"] == 25020.0
    print(f"✅ +1.75R expansion: Trailing SL ratcheted to {trade['current_sl']} (+0.5R = +₹1,000 profit locked!)")

    # 5. Candle 4: High reaches 25095 (+2.37R) -> Trailing Ratchet locks +1.0R profit!
    # raw_lock = 2.37 - 1.0 = 1.37 -> floor(1.37/0.5)*0.5 = 1.0R -> SL = 25000 + 1.0*40 = 25040.0
    evs = trader.check_trades_with_candle("NIFTY 50", make_candle(ts + 1200, 25065, 25095, 25060, 25090))
    trade = trader.get_open_trades().get(trade_id)
    assert trade["trailed_r"] == 1.0
    assert trade["current_sl"] == 25040.0
    print(f"✅ +2.37R expansion: Trailing SL ratcheted to {trade['current_sl']} (+1.0R = +₹2,000 profit locked!)")

    # 6. Candle 5: Sudden crash / retracement! Low drops to 25030 (breaches trailed SL 25040)
    evs = trader.check_trades_with_candle("NIFTY 50", make_candle(ts + 1500, 25090, 25092, 25030, 25035))
    closed_ev = next((e for e in evs if e.get("event") == "TRADE_CLOSED"), None)
    assert closed_ev is not None, "Trade should be closed"
    assert closed_ev["reason"] == "TRAILING_SL_HIT"
    assert closed_ev["pnl"] >= 2000.0, f"P&L should be >= ₹2,000 locked profit, got {closed_ev['pnl']}"
    print(f"✅ Sudden reversal stopped by Trailing SL! Reason: {closed_ev['reason']} | Secured Profit: +₹{closed_ev['pnl']:,.0f} 💰")


def test_sell_trailing_ratchet():
    print("\n======================================================================")
    print("--- TEST 2: SELL Trailing Stop Loss Ratchet (+1.0R BE -> +0.5R -> +1.0R) ---")
    print("======================================================================")

    config = {
        "trade_management": {
            "mode": "ict_pro",
            "enable_breakeven_at_1r": True,
            "breakeven_trigger_r": 1.0,
            "enable_trailing_sl": True,
            "trailing_activation_r": 1.5,
            "trailing_distance_r": 1.0,
            "trailing_step_r": 0.5,
            "enable_near_tp_lock": True,
            "near_tp_threshold_pct": 85.0
        }
    }

    os.environ["PAPER_MODE"] = "true"
    trader = KiteTrader(config)
    trader.stop_monitoring()
    ts = int(datetime(2026, 9, 21, 9, 30, tzinfo=IST).timestamp())

    # 1. Place SELL Trade: Spot 25000, SL 25040 (Risk = 40 pts), TP 24880 (3R)
    trade_id = trader.place_order(
        signal={
            "signal": "SELL",
            "entry_price": 25000.0,
            "sl_price": 25040.0,
            "tp_price": 24880.0,
            "model": "Turtle Soup Model (PDH)"
        },
        instrument_name="NIFTY 50",
        lots=1
    )
    assert trade_id is not None
    trade = trader.get_open_trades().get(trade_id)
    assert trade["current_sl"] == 25040.0
    print(f"✅ SELL Trade entered: Entry 25000, Initial SL {trade['current_sl']}, Risk = 40 pts")

    # 2. Low reaches 24955 (+1.1R) -> BE triggered! SL = 25000.0
    trader.check_trades_with_candle("NIFTY 50", make_candle(ts + 600, 24980, 24990, 24955, 24960))
    trade = trader.get_open_trades().get(trade_id)
    assert trade["breakeven_moved"] is True
    assert trade["current_sl"] == 25000.0
    print(f"✅ +1.1R drop: Breakeven triggered! SL moved to {trade['current_sl']} (Risk = ₹0)")

    # 3. Low drops to 24925 (+1.87R) -> Trailing Ratchet locks +0.5R profit!
    # SL = 25000 - 0.5*40 = 24980.0
    trader.check_trades_with_candle("NIFTY 50", make_candle(ts + 900, 24960, 24965, 24925, 24930))
    trade = trader.get_open_trades().get(trade_id)
    assert trade["trailed_r"] == 0.5
    assert trade["current_sl"] == 24980.0
    print(f"✅ +1.87R drop: Trailing SL ratcheted to {trade['current_sl']} (+0.5R = +₹1,000 profit locked!)")

    # 4. Low drops to 24905 (+2.37R) -> Trailing Ratchet locks +1.0R profit!
    # SL = 25000 - 1.0*40 = 24960.0
    trader.check_trades_with_candle("NIFTY 50", make_candle(ts + 1200, 24930, 24935, 24905, 24910))
    trade = trader.get_open_trades().get(trade_id)
    assert trade["trailed_r"] == 1.0
    assert trade["current_sl"] == 24960.0
    print(f"✅ +2.37R drop: Trailing SL ratcheted to {trade['current_sl']} (+1.0R = +₹2,000 profit locked!)")

    # 5. Retracement bounce up to 24970 (breaches trailed SL 24960)
    evs = trader.check_trades_with_candle("NIFTY 50", make_candle(ts + 1500, 24910, 24970, 24908, 24965))
    closed_ev = next((e for e in evs if e.get("event") == "TRADE_CLOSED"), None)
    assert closed_ev is not None
    assert closed_ev["reason"] == "TRAILING_SL_HIT"
    assert closed_ev["pnl"] >= 2000.0
    print(f"✅ Reversal stopped by Trailing SL! Reason: {closed_ev['reason']} | Secured Profit: +₹{closed_ev['pnl']:,.0f} 💰")


if __name__ == "__main__":
    test_buy_trailing_ratchet()
    test_sell_trailing_ratchet()
    print("\n🎯 ALL INSTITUTIONAL TRAILING STOP LOSS TESTS PASSED PERFECTLY!")
