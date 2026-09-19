"""
Backtest NIFTY 5m: 2025 - 2026 using Institutional ICT Strategy.
Simulates day-by-day rolling execution matching live bot behavior:
- 5-day rolling window for accurate PDH/PDL and HTF structure without lookahead bias.
- Institutional Confluence Matrix filter (Score >= 75 / Grade A/A+).
- RiskGate limits: Max 2 concurrent positions, Daily loss killswitch (-₹2,000).
- Pro Desk Trade Management:
  * +1.0R Breakeven dynamic adjustment (Risk = 0)
  * 85% Near-TP profit lock on candle stall/rejection
  * 15:15 IST intraday squareoff
- Lot size: 1 lot = 50 qty.
"""
import os
import sys
from datetime import datetime, time
import zoneinfo
import yaml
import pandas as pd
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.indicator.engine import ICTPredictiveEngine
from src.indicator.models import Candle

IST = zoneinfo.ZoneInfo("Asia/Kolkata")
CSV_PATH = "/Users/saivarun/Documents/Codex/2026-09-06/files-pasted-by-the-user-you/ict_trading_engine/ict_market_data/NIFTY_5m.csv"
LOT_SIZE = 50

def load_yaml(filename):
    with open(os.path.join(BASE_DIR, "config", filename)) as f:
        return yaml.safe_load(f) or {}

def run_backtest():
    settings_cfg = load_yaml("settings.yaml")
    engine = ICTPredictiveEngine(settings_cfg)
    
    trade_mgmt = settings_cfg.get("trade_management", {})
    enable_be = trade_mgmt.get("enable_breakeven_at_1r", True)
    be_r = float(trade_mgmt.get("breakeven_trigger_r", 1.0))
    enable_near_tp = trade_mgmt.get("enable_near_tp_lock", True)
    near_tp_pct = float(trade_mgmt.get("near_tp_threshold_pct", 85.0))
    stall_wick_pct = float(trade_mgmt.get("rejection_stall_wick_pct", 20.0))
    allow_pyramiding = trade_mgmt.get("allow_pyramiding_if_risk_free", True)

    df = pd.read_csv(CSV_PATH)
    df["dt"] = pd.to_datetime(df["timestamp"])
    df["date"] = df["dt"].dt.date
    unique_dates = sorted(df["date"].unique())

    all_trades = []
    day_summaries = []
    cum_pnl = 0.0

    # Start from day 1 so day 0 provides PDH/PDL
    for i in range(1, len(unique_dates)):
        target_date = unique_dates[i]
        hist_dates = unique_dates[max(0, i - 4):i + 1]
        sub_df = df[df["date"].isin(hist_dates)].copy()

        candles = [
            Candle(
                timestamp=int(r["dt"].timestamp()),
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                volume=float(r["volume"])
            )
            for _, r in sub_df.iterrows()
        ]

        res = engine.evaluate(candles)
        raw_signals = res.get("signals", [])
        
        # Filter to target day and sort chronologically
        day_signals = []
        for s in raw_signals:
            sig_dt = datetime.fromtimestamp(s["time"], tz=IST)
            if sig_dt.date() == target_date:
                # Find bar index in current slice
                b_idx = next((idx for idx, c in enumerate(candles) if c.timestamp == s["time"]), None)
                day_signals.append({**s, "dt": sig_dt, "bar_idx": b_idx})

        day_signals.sort(key=lambda s: s["time"])

        # Intraday simulation state
        day_realized_pnl = 0.0
        open_positions = [] # list of active trade dicts
        loss_limit_hit = False

        # Get day candles only for bar-by-bar progression
        day_bar_indices = [idx for idx, c in enumerate(candles) if datetime.fromtimestamp(c.timestamp, tz=IST).date() == target_date]
        if not day_bar_indices:
            continue

        for bar_idx in day_bar_indices:
            c = candles[bar_idx]
            bar_dt = datetime.fromtimestamp(c.timestamp, tz=IST)
            bar_time = bar_dt.time()

            # 1. Update open positions with current candle
            closed_this_bar = []
            for t in open_positions:
                direction = t["direction"]
                entry = t["entry"]
                sl = t["current_sl"]
                tp = t["tp"]
                risk_pts = t["risk_pts"]
                t["bars_held"] += 1

                # Square-off at or after 15:15
                if bar_time >= time(15, 15):
                    exit_price = c.close
                    reason = "SQUAREOFF"
                    pts = (exit_price - entry) if direction == "BUY" else (entry - exit_price)
                    pnl = round(pts * LOT_SIZE, 2)
                    t.update({"exit_price": exit_price, "reason": reason, "pts": pts, "pnl": pnl, "exit_time": bar_dt.strftime("%H:%M")})
                    closed_this_bar.append(t)
                    continue

                if direction == "BUY":
                    # Check SL
                    if c.low <= sl:
                        reason = "BREAKEVEN" if t["breakeven_moved"] else "SL"
                        exit_price = sl
                        pts = 0.0 if reason == "BREAKEVEN" else (sl - entry)
                        pnl = round(pts * LOT_SIZE, 2)
                        t.update({"exit_price": exit_price, "reason": reason, "pts": pts, "pnl": pnl, "exit_time": bar_dt.strftime("%H:%M")})
                        closed_this_bar.append(t)
                        continue
                    # Check TP
                    if c.high >= tp:
                        reason = "TP"
                        exit_price = tp
                        pts = tp - entry
                        pnl = round(pts * LOT_SIZE, 2)
                        t.update({"exit_price": exit_price, "reason": reason, "pts": pts, "pnl": pnl, "exit_time": bar_dt.strftime("%H:%M")})
                        closed_this_bar.append(t)
                        continue
                    # Check Breakeven at +1.0R
                    if enable_be and not t["breakeven_moved"]:
                        if c.high >= entry + (be_r * risk_pts):
                            t["breakeven_moved"] = True
                            t["current_sl"] = entry
                    # Check Near-TP profit lock (85% of target with stall wick)
                    if enable_near_tp and not t.get("near_tp_booked"):
                        near_tp_level = entry + (near_tp_pct / 100.0) * (tp - entry)
                        if c.high >= near_tp_level:
                            c_range = max(c.high - c.low, 0.05)
                            upper_wick = c.high - max(c.open, c.close)
                            if (upper_wick / c_range) * 100.0 >= stall_wick_pct or c.close < c.high - 0.25 * c_range:
                                reason = "NEAR_TP"
                                exit_price = c.close
                                pts = exit_price - entry
                                pnl = round(pts * LOT_SIZE, 2)
                                t.update({"exit_price": exit_price, "reason": reason, "pts": pts, "pnl": pnl, "exit_time": bar_dt.strftime("%H:%M")})
                                closed_this_bar.append(t)
                                continue

                elif direction == "SELL":
                    # Check SL
                    if c.high >= sl:
                        reason = "BREAKEVEN" if t["breakeven_moved"] else "SL"
                        exit_price = sl
                        pts = 0.0 if reason == "BREAKEVEN" else (entry - sl)
                        pnl = round(pts * LOT_SIZE, 2)
                        t.update({"exit_price": exit_price, "reason": reason, "pts": pts, "pnl": pnl, "exit_time": bar_dt.strftime("%H:%M")})
                        closed_this_bar.append(t)
                        continue
                    # Check TP
                    if c.low <= tp:
                        reason = "TP"
                        exit_price = tp
                        pts = entry - tp
                        pnl = round(pts * LOT_SIZE, 2)
                        t.update({"exit_price": exit_price, "reason": reason, "pts": pts, "pnl": pnl, "exit_time": bar_dt.strftime("%H:%M")})
                        closed_this_bar.append(t)
                        continue
                    # Check Breakeven at +1.0R
                    if enable_be and not t["breakeven_moved"]:
                        if c.low <= entry - (be_r * risk_pts):
                            t["breakeven_moved"] = True
                            t["current_sl"] = entry
                    # Check Near-TP profit lock (85% of target with stall wick)
                    if enable_near_tp and not t.get("near_tp_booked"):
                        near_tp_level = entry - (near_tp_pct / 100.0) * (entry - tp)
                        if c.low <= near_tp_level:
                            c_range = max(c.high - c.low, 0.05)
                            lower_wick = min(c.open, c.close) - c.low
                            if (lower_wick / c_range) * 100.0 >= stall_wick_pct or c.close > c.low + 0.25 * c_range:
                                reason = "NEAR_TP"
                                exit_price = c.close
                                pts = entry - exit_price
                                pnl = round(pts * LOT_SIZE, 2)
                                t.update({"exit_price": exit_price, "reason": reason, "pts": pts, "pnl": pnl, "exit_time": bar_dt.strftime("%H:%M")})
                                closed_this_bar.append(t)
                                continue

            for t in closed_this_bar:
                open_positions.remove(t)
                day_realized_pnl += t["pnl"]
                all_trades.append(t)
                if day_realized_pnl <= -2000:
                    loss_limit_hit = True

            # 2. Check if a signal fired on this bar
            matching_signals = [s for s in day_signals if s["bar_idx"] == bar_idx]
            for sig in matching_signals:
                if loss_limit_hit:
                    continue
                if bar_time < time(9, 20) or bar_time >= time(15, 15):
                    continue
                if len(open_positions) >= 2:
                    continue
                if open_positions:
                    # Pyramiding check
                    if open_positions[0]["direction"] != sig["signal"]:
                        continue
                    if not allow_pyramiding or not open_positions[0]["breakeven_moved"]:
                        continue

                # Open trade
                entry_p = float(sig["entry_price"])
                sl_p = float(sig["sl_price"])
                tp_p = float(sig["tp_price"])
                trade_dict = {
                    "date": str(target_date),
                    "entry_time": bar_dt.strftime("%H:%M"),
                    "direction": sig["signal"],
                    "model": sig.get("model", "ICT Model"),
                    "grade": sig.get("grade", "A"),
                    "score": sig.get("confluence_score", 0),
                    "entry": entry_p,
                    "sl": sl_p,
                    "tp": tp_p,
                    "current_sl": sl_p,
                    "risk_pts": abs(entry_p - sl_p),
                    "breakeven_moved": False,
                    "bars_held": 0,
                    "qty": LOT_SIZE
                }
                open_positions.append(trade_dict)

        # End of day summary
        day_trades = [t for t in all_trades if t["date"] == str(target_date)]
        day_pts = sum(t["pts"] for t in day_trades)
        day_pnl = sum(t["pnl"] for t in day_trades)
        cum_pnl += day_pnl

        wins = len([t for t in day_trades if t["reason"] in ("TP", "NEAR_TP") and t["pts"] > 0])
        losses = len([t for t in day_trades if t["reason"] == "SL" or t["pts"] < 0])
        scratches = len([t for t in day_trades if t["reason"] == "BREAKEVEN" or t["pts"] == 0])

        day_summaries.append({
            "date": str(target_date),
            "trades": len(day_trades),
            "wins": wins,
            "losses": losses,
            "scratches": scratches,
            "points": round(day_pts, 2),
            "pnl": round(day_pnl, 2),
            "cum_pnl": round(cum_pnl, 2)
        })

    return day_summaries, all_trades

if __name__ == "__main__":
    day_summaries, all_trades = run_backtest()
    trades_df = pd.DataFrame(all_trades)
    days_df = pd.DataFrame(day_summaries)
    
    # Save CSVs
    os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
    days_df.to_csv(os.path.join(BASE_DIR, "logs", "nifty_daywise_pnl.csv"), index=False)
    trades_df.to_csv(os.path.join(BASE_DIR, "logs", "nifty_all_trades.csv"), index=False)
    
    print(f"Total days simulated: {len(days_df)}")
    print(f"Total trades: {len(trades_df)}")
    active_days = days_df[days_df['trades'] > 0]
    print(f"Active trading days: {len(active_days)}")
    print(f"Winning days: {len(active_days[active_days['pnl'] > 0])}")
    print(f"Losing days: {len(active_days[active_days['pnl'] < 0])}")
    print(f"Breakeven days: {len(active_days[active_days['pnl'] == 0])}")
    print(f"Total Net P&L: ₹{days_df['cum_pnl'].iloc[-1]:+,.2f}")
    print(f"Total Points: {days_df['points'].sum():+,.2f} pts")
