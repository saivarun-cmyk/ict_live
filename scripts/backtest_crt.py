#!/usr/bin/env python3
"""
Backtest Candle Range Theory (CRT) on NIFTY 5-minute data.
Tests:
1. 15m Candle Range Theory (Previous 15m High/Low sweep & fade)
2. 1-Hour Candle Range Theory (Previous 1H High/Low sweep & fade)
3. Trend-Aligned CRT (Only trade CRT setups aligned with macro order flow)
"""
import os
import sys
from datetime import datetime, time
import zoneinfo
import pandas as pd
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.indicator.models import Candle
from src.data.candle_builder import aggregate_candles

IST = zoneinfo.ZoneInfo("Asia/Kolkata")
CSV_PATH = "/Users/saivarun/Documents/Codex/2026-09-06/files-pasted-by-the-user-you/ict_trading_engine/ict_market_data/NIFTY_5m.csv"
LOT_SIZE = 50

def run_crt_backtest(crt_timeframe_minutes=15, enforce_trend=False, min_rr=1.5):
    df = pd.read_csv(CSV_PATH)
    df["dt"] = pd.to_datetime(df["timestamp"])
    df["date"] = df["dt"].dt.date
    unique_dates = sorted(df["date"].unique())

    all_trades = []
    day_summaries = []

    for i in range(1, len(unique_dates)):
        target_date = unique_dates[i]
        hist_dates = unique_dates[max(0, i - 2):i + 1]
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

        # Aggregate higher timeframe candles for CRT ranges
        htf_candles = aggregate_candles(candles, target_minutes=crt_timeframe_minutes)
        if len(htf_candles) < 3:
            continue

        # Build lookup of closed HTF candles
        # Map timestamp to previous closed HTF candle range
        target_sec = crt_timeframe_minutes * 60

        day_candles = [c for c in candles if datetime.fromtimestamp(c.timestamp, tz=IST).date() == target_date]
        if not day_candles:
            continue

        open_positions = []
        day_trades = []
        day_pnl = 0.0

        for c_idx, c in enumerate(day_candles):
            bar_dt = datetime.fromtimestamp(c.timestamp, tz=IST)
            bar_time = bar_dt.time()

            # 1. Update open positions
            closed_this_bar = []
            for t in open_positions:
                direction = t["direction"]
                entry = t["entry"]
                sl = t["current_sl"]
                tp = t["tp"]
                t["bars_held"] += 1

                # Intraday squareoff at 15:15
                if bar_time >= time(15, 15):
                    exit_price = c.close
                    pts = (exit_price - entry) if direction == "BUY" else (entry - exit_price)
                    pnl = round(pts * LOT_SIZE, 2)
                    t.update({"exit_price": exit_price, "reason": "SQUAREOFF", "pts": pts, "pnl": pnl})
                    closed_this_bar.append(t)
                    continue

                if direction == "BUY":
                    if c.low <= sl:
                        reason = "BREAKEVEN" if t["breakeven_moved"] else "SL"
                        exit_price = sl
                        pts = 0.0 if reason == "BREAKEVEN" else (sl - entry)
                        pnl = round(pts * LOT_SIZE, 2)
                        t.update({"exit_price": exit_price, "reason": reason, "pts": pts, "pnl": pnl})
                        closed_this_bar.append(t)
                        continue
                    if c.high >= tp:
                        exit_price = tp
                        pts = tp - entry
                        pnl = round(pts * LOT_SIZE, 2)
                        t.update({"exit_price": exit_price, "reason": "TP", "pts": pts, "pnl": pnl})
                        closed_this_bar.append(t)
                        continue
                    # Move to Breakeven at +1.0R
                    gain_r = (c.high - entry) / max(1.0, t["risk_pts"])
                    if gain_r >= 1.0 and not t["breakeven_moved"]:
                        t["current_sl"] = entry
                        t["breakeven_moved"] = True

                elif direction == "SELL":
                    if c.high >= sl:
                        reason = "BREAKEVEN" if t["breakeven_moved"] else "SL"
                        exit_price = sl
                        pts = 0.0 if reason == "BREAKEVEN" else (entry - sl)
                        pnl = round(pts * LOT_SIZE, 2)
                        t.update({"exit_price": exit_price, "reason": reason, "pts": pts, "pnl": pnl})
                        closed_this_bar.append(t)
                        continue
                    if c.low <= tp:
                        exit_price = tp
                        pts = entry - tp
                        pnl = round(pts * LOT_SIZE, 2)
                        t.update({"exit_price": exit_price, "reason": "TP", "pts": pts, "pnl": pnl})
                        closed_this_bar.append(t)
                        continue
                    # Move to Breakeven at +1.0R
                    gain_r = (entry - c.low) / max(1.0, t["risk_pts"])
                    if gain_r >= 1.0 and not t["breakeven_moved"]:
                        t["current_sl"] = entry
                        t["breakeven_moved"] = True

            for cl in closed_this_bar:
                open_positions.remove(cl)
                day_trades.append(cl)
                day_pnl += cl["pnl"]

            # 2. Look for new CRT signals (Limit 1 open position at a time)
            # Skip first bar 09:15 and after 14:45
            if len(open_positions) >= 1 or bar_time < time(9, 20) or bar_time > time(14, 45):
                continue

            # Find previous completed HTF candle
            last_htf = None
            for h in reversed(htf_candles):
                if c.timestamp >= (h.timestamp + target_sec):
                    last_htf = h
                    break

            if last_htf is None:
                continue

            pch = last_htf.high  # Previous Candle High
            pcl = last_htf.low   # Previous Candle Low
            p_ce = (pch + pcl) / 2.0  # 50% Consequent Encroachment

            # Trend filter if enabled
            trend_ok_buy = True
            trend_ok_sell = True
            if enforce_trend:
                # 20-period simple moving baseline
                htf_closes = [h.close for h in htf_candles if h.timestamp < c.timestamp]
                if len(htf_closes) >= 10:
                    avg_c = np.mean(htf_closes[-10:])
                    trend_ok_buy = c.close > avg_c
                    trend_ok_sell = c.close < avg_c

            # CRT SETUP 1: BEARISH CRT SWEEP & FADE
            # Price swept Previous Candle High, but 5m bar rejected and closed back below PCH
            if c.high > pch and c.close < pch and trend_ok_sell:
                # Require upper rejection wick >= 20%
                total_range = c.high - c.low
                upper_wick = c.high - max(c.open, c.close)
                wick_pct = (upper_wick / total_range * 100.0) if total_range > 0 else 0
                if wick_pct >= 20.0:
                    entry = c.close
                    sl = float(round(c.high + 5.0, 2))  # SL just above sweep wick
                    risk_pts = sl - entry
                    if risk_pts >= 5.0:
                        # Target is Previous Candle Low (or 50% CE if PCL gives > 3R)
                        target = pcl
                        if (entry - target) < (risk_pts * min_rr):
                            target = entry - (risk_pts * min_rr)
                        tp = float(round(target, 2))
                        open_positions.append({
                            "date": target_date.strftime("%Y-%m-%d"),
                            "time": bar_dt.strftime("%H:%M"),
                            "direction": "SELL",
                            "model": f"{crt_timeframe_minutes}m CRT Sweep High",
                            "entry": entry,
                            "sl": sl,
                            "current_sl": sl,
                            "tp": tp,
                            "risk_pts": risk_pts,
                            "breakeven_moved": False,
                            "bars_held": 0
                        })

            # CRT SETUP 2: BULLISH CRT SWEEP & FADE
            # Price swept Previous Candle Low, but 5m bar rejected and closed back above PCL
            elif c.low < pcl and c.close > pcl and trend_ok_buy:
                total_range = c.high - c.low
                lower_wick = min(c.open, c.close) - c.low
                wick_pct = (lower_wick / total_range * 100.0) if total_range > 0 else 0
                if wick_pct >= 20.0:
                    entry = c.close
                    sl = float(round(c.low - 5.0, 2))  # SL just below sweep wick
                    risk_pts = entry - sl
                    if risk_pts >= 5.0:
                        target = pch
                        if (target - entry) < (risk_pts * min_rr):
                            target = entry + (risk_pts * min_rr)
                        tp = float(round(target, 2))
                        open_positions.append({
                            "date": target_date.strftime("%Y-%m-%d"),
                            "time": bar_dt.strftime("%H:%M"),
                            "direction": "BUY",
                            "model": f"{crt_timeframe_minutes}m CRT Sweep Low",
                            "entry": entry,
                            "sl": sl,
                            "current_sl": sl,
                            "tp": tp,
                            "risk_pts": risk_pts,
                            "breakeven_moved": False,
                            "bars_held": 0
                        })

        all_trades.extend(day_trades)

    # Compute Statistics
    if not all_trades:
        return {"error": "No trades found"}

    df_res = pd.DataFrame(all_trades)
    total_trades = len(df_res)
    wins = df_res[df_res["pnl"] > 0]
    losses = df_res[df_res["pnl"] < 0]
    scratches = df_res[df_res["pnl"] == 0]

    win_rate = (len(wins) / total_trades) * 100.0
    net_pnl = df_res["pnl"].sum()
    avg_win = wins["pnl"].mean() if len(wins) > 0 else 0.0
    avg_loss = abs(losses["pnl"].mean()) if len(losses) > 0 else 0.0
    rr_realized = (avg_win / avg_loss) if avg_loss > 0 else 0.0
    profit_factor = (wins["pnl"].sum() / abs(losses["pnl"].sum())) if len(losses) > 0 and abs(losses["pnl"].sum()) > 0 else 999.0

    return {
        "tf": f"{crt_timeframe_minutes}m",
        "trend_filter": enforce_trend,
        "total_trades": total_trades,
        "wins": len(wins),
        "losses": len(losses),
        "scratches": len(scratches),
        "win_rate_pct": round(win_rate, 1),
        "net_pnl": round(net_pnl, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "realized_rr": round(rr_realized, 2),
        "profit_factor": round(profit_factor, 2)
    }

if __name__ == "__main__":
    print("================================================================================")
    print("BACKTESTING CANDLE RANGE THEORY (CRT) ON 1-YEAR NIFTY 5M DATA (1 LOT = 50 QTY)")
    print("================================================================================")

    # Test 1: 15m CRT (without trend filter)
    r1 = run_crt_backtest(crt_timeframe_minutes=15, enforce_trend=False)
    print("\n1. 15-Minute Candle Range Theory (Pure Sweep & Fade):")
    for k, v in r1.items():
        print(f"   {k}: {v}")

    # Test 2: 15m CRT (with Trend Alignment Filter)
    r2 = run_crt_backtest(crt_timeframe_minutes=15, enforce_trend=True)
    print("\n2. 15-Minute Candle Range Theory (Trend-Aligned):")
    for k, v in r2.items():
        print(f"   {k}: {v}")

    # Test 3: 60m / 1-Hour CRT (without trend filter)
    r3 = run_crt_backtest(crt_timeframe_minutes=60, enforce_trend=False)
    print("\n3. 60-Minute (1-Hour) Candle Range Theory (Pure Sweep & Fade):")
    for k, v in r3.items():
        print(f"   {k}: {v}")

    # Test 4: 60m / 1-Hour CRT (with Trend Alignment Filter)
    r4 = run_crt_backtest(crt_timeframe_minutes=60, enforce_trend=True)
    print("\n4. 60-Minute (1-Hour) Candle Range Theory (Trend-Aligned):")
    for k, v in r4.items():
        print(f"   {k}: {v}")
