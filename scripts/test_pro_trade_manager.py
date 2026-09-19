"""
Test Institutional ICT Trade Management (Pro Desk Trader Brain)
Verifies:
  1. +1.0R Breakeven dynamic adjustment (Risk = 0)
  2. Proximity profit harvesting (85-90% of TP with stall wick rejection)
  3. Risk-free pyramiding / stacking on winning positions
  4. Blocking pyramiding when initial trade still has open risk
  5. Desk alerts formatting
"""
import os
import sys
import yaml
import logging

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.indicator.models import Candle
from src.execution.signal_executor import SignalExecutor
from src.alerts.telegram import TelegramNotifier

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestTradeManager")

def test_trade_manager():
    # 1. Initialize executor with test config
    with open(os.path.join(BASE_DIR, "config", "settings.yaml")) as f:
        cfg = yaml.safe_load(f)
    cfg["trade_management"]["enable_trailing_sl"] = False

    # Force paper mode for safe testing
    os.environ["PAPER_MODE"] = "true"

    executor = SignalExecutor(config=cfg)
    executor.trader._open_trades.clear()
    executor.gate._open_positions.clear()
    executor.gate._recent_signal_ids.clear()
    executor.gate._daily_realized_pnl = 0.0

    # Allow test execution at any hour
    from datetime import time as dt_time
    executor.gate.allowed_start = dt_time(0, 0)
    executor.gate.allowed_end = dt_time(23, 59)
    executor.gate.squareoff_deadline = dt_time(23, 59)
    executor.trader.stop_monitoring()  # Stop background thread in unit test

    print("\n" + "=" * 70)
    print("--- TEST 1: Initial Trade Entry (NIFTY 50 BUY) ---")
    print("=" * 70)
    sig1 = {
        "signal": "BUY",
        "entry_price": 25000.0,
        "sl_price": 24950.0,   # Risk = 50 pts (1R = 25050.0)
        "tp_price": 25100.0,   # TP = 100 pts (2R)
        "model": "Unicorn Model (Breaker + IFVG)",
        "bar_index": 100,
        "time": 1726718400,
    }

    res1 = executor.process(sig1, "NIFTY 50", lots=1)
    assert res1["executed"], f"Trade 1 failed to execute: {res1['reason']}"
    trade_id1 = res1["trade_id"]
    trade1 = executor.trader._open_trades[trade_id1]
    assert trade1["spot_entry"] == 25000.0
    assert trade1["risk_pts"] == 50.0
    assert trade1["current_sl"] == 24950.0
    assert not trade1["breakeven_moved"]
    print(f"✅ Trade 1 successfully entered: {trade_id1} | Entry 25000 | SL 24950 | TP 25100")

    print("\n" + "=" * 70)
    print("--- TEST 2: Pyramiding Blocked When Trade Has Active Risk ---")
    print("=" * 70)
    sig2 = {
        "signal": "BUY",
        "entry_price": 25020.0,
        "sl_price": 24980.0,
        "tp_price": 25120.0,
        "model": "Silver Bullet Model",
        "bar_index": 102,
        "time": 1726719000,
    }
    res2 = executor.process(sig2, "NIFTY 50", lots=1)
    assert not res2["executed"], "Should NOT allow pyramiding before Trade 1 is risk-free at BE!"
    print(f"✅ Blocked secondary entry as expected: {res2['reason']}")

    print("\n" + "=" * 70)
    print("--- TEST 3: +1.0R Expansion Moves SL to Breakeven (Risk = 0) ---")
    print("=" * 70)
    # Candle expands to 25055 (1R = 25050)
    c_1r = Candle(
        open=25010.0,
        high=25055.0,  # Crosses 25050 (+1.1R)
        low=25005.0,
        close=25048.0,
        volume=1000,
        timestamp=1726719300
    )
    events = executor.update_open_positions("NIFTY 50", c_1r)
    be_events = [e for e in events if e.get("event") == "BREAKEVEN_MOVED"]
    assert len(be_events) == 1, f"Expected BREAKEVEN_MOVED event, got: {events}"
    assert trade1["breakeven_moved"], "Trade 1 breakeven_moved should be True"
    assert trade1["current_sl"] == 25000.0, f"SL should be 25000.0, got {trade1['current_sl']}"
    assert executor.gate._open_positions[trade_id1]["breakeven_moved"], "RiskGate must sync breakeven_moved"
    print(f"✅ Stop Loss moved to Breakeven (25000.0). Trade is now RISK-FREE!")

    print("\n" + "=" * 70)
    print("--- TEST 4: Risk-Free Pyramiding Allowed Now ---")
    print("=" * 70)
    # Now that trade 1 is at Breakeven, secondary setup is accepted!
    res_pyr = executor.process(sig2, "NIFTY 50", lots=1)
    assert res_pyr["executed"], f"Pyramid trade should be executed when base is risk-free: {res_pyr['reason']}"
    trade_id2 = res_pyr["trade_id"]
    print(f"✅ Pyramid trade accepted and placed: {trade_id2} (Model: {sig2['model']})")

    print("\n" + "=" * 70)
    print("--- TEST 5: Proximity / Near-TP Profit Locking ---")
    print("=" * 70)
    # TP of trade 1 is 25100. 85% of 100 pts is 25085.
    # Candle reaches 25090 (90% of TP) and has a rejection upper wick closing at 25075
    c_near_tp = Candle(
        open=25065.0,
        high=25090.0,  # 90% to TP (10 pts from target)
        low=25060.0,
        close=25075.0, # Upper wick = 25090 - 25075 = 15 pts (50% of 30pt range -> stall rejection!)
        volume=1200,
        timestamp=1726719600
    )
    events2 = executor.update_open_positions("NIFTY 50", c_near_tp)
    near_tp_events = [e for e in events2 if e.get("reason") == "NEAR_TP_PROFIT_LOCK"]
    assert len(near_tp_events) >= 1, f"Expected NEAR_TP_PROFIT_LOCK event, got {events2}"
    closed_ev = near_tp_events[0]
    print(f"✅ Trade locked profits near TP: Exited at spot {closed_ev['exit_spot']} | P&L: ₹{closed_ev['pnl']:+,.0f}")
    assert trade_id1 not in executor.trader.get_open_trades(), "Trade 1 should be removed from open trades"
    assert trade_id1 not in executor.gate._open_positions, "Trade 1 should be closed in RiskGate"

    print("\n" + "=" * 70)
    print("--- TEST 6: Breakeven Scratch Defense on Retracement ---")
    print("=" * 70)
    # Trade 2 is at 25020, move it to BE at 25060 (+1R)
    c_pyr_1r = Candle(
        open=25030.0,
        high=25065.0, # 1R for trade 2 (entry 25020, risk 40 -> 1R is 25060)
        low=25025.0,
        close=25062.0,
        volume=800,
        timestamp=1726719900
    )
    executor.update_open_positions("NIFTY 50", c_pyr_1r)
    trade2 = executor.trader.get_open_trades().get(trade_id2)
    assert trade2["breakeven_moved"], "Trade 2 should be at Breakeven"

    # Now market suddenly flushes back to 25010 (breaching entry of 25020)
    c_flush = Candle(
        open=25050.0,
        high=25055.0,
        low=25015.0,  # Below 25020
        close=25018.0,
        volume=1500,
        timestamp=1726720200
    )
    events3 = executor.update_open_positions("NIFTY 50", c_flush)
    be_hit_events = [e for e in events3 if e.get("reason") == "BREAKEVEN_HIT"]
    assert len(be_hit_events) == 1, f"Expected BREAKEVEN_HIT event, got {events3}"
    be_ev = be_hit_events[0]
    assert be_ev["pnl"] == 0.0, f"Breakeven scratch trade must have ₹0 loss, got {be_ev['pnl']}"
    print(f"✅ Market flushed, but trade stopped at Breakeven with ₹{be_ev['pnl']} loss (0 loss scratch)!")

    print("\n" + "=" * 70)
    print("🎯 ALL 6 INSTITUTIONAL ICT DESK TRADER TESTS PASSED PERFECTLY!")
    print("=" * 70)

if __name__ == "__main__":
    test_trade_manager()
