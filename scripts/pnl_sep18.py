"""
Sep 18 P&L Calculator
For every signal that fired today, checks subsequent candles to determine
whether TP or SL was hit first, then computes actual P&L.
"""
import sys
import os
from datetime import datetime
import zoneinfo
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.indicator.engine import ICTPredictiveEngine
from src.data.upstox_client import UpstoxClient

IST = zoneinfo.ZoneInfo("Asia/Kolkata")
SEP18 = "2026-09-18"

# ── Lot sizes / contract multipliers for P&L (adjust as needed) ──────────
LOT_SIZES = {
    "NIFTY 50":               50,   # 1 lot = 50 qty (options)
    "BANK NIFTY":             15,   # 1 lot = 15 qty
    "SENSEX":                 10,
    "Reliance Industries":    1,
    "HDFC Bank":              1,
}
LOTS_TRADED = 1   # assume 1 lot per signal


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f) or {}


def ts_ist(ts):
    return datetime.fromtimestamp(ts, tz=IST).strftime("%H:%M")


def check_outcome(signal_dict, candles, signal_bar_idx):
    """
    Walks forward from signal_bar_idx+1.
    Returns ('TP', bars_held) | ('SL', bars_held) | ('OPEN', bars_held)
    """
    entry  = signal_dict["entry_price"]
    sl     = signal_dict["sl_price"]
    tp     = signal_dict["tp_price"]
    direction = signal_dict["signal"]   # "BUY" or "SELL"

    for i in range(signal_bar_idx + 1, len(candles)):
        c = candles[i]
        bars = i - signal_bar_idx
        if direction == "BUY":
            if c.high >= tp:
                return "TP", bars, tp
            if c.low <= sl:
                return "SL", bars, sl
        elif direction == "SELL":
            if c.low <= tp:
                return "TP", bars, tp
            if c.high >= sl:
                return "SL", bars, sl

    return "OPEN", len(candles) - signal_bar_idx - 1, candles[-1].close


def pnl_points(outcome, entry, hit_price, direction):
    if direction == "BUY":
        return round(hit_price - entry, 2)
    else:
        return round(entry - hit_price, 2)


def main():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg  = load_yaml(os.path.join(base, "config", "settings.yaml"))
    inst_cfg = load_yaml(os.path.join(base, "config", "instruments.yaml"))

    engine = ICTPredictiveEngine(cfg)
    client = UpstoxClient()

    all_instruments = [
        i for i in inst_cfg.get("indices", []) + inst_cfg.get("stocks", [])
        if i.get("enabled")
    ]

    timeframes = ["5m", "15m"]
    tf_map = {"5m": "5minute", "15m": "15minute"}

    trades = []

    print("=" * 72)
    print("  ICT ENGINE — Sep 18 TRADE OUTCOME & P&L REPORT")
    print(f"  Run at: {datetime.now(tz=IST).strftime('%H:%M  %d-%b-%Y IST')}")
    print("=" * 72)

    for inst in all_instruments:
        name  = inst["name"]
        key   = inst["instrument_key"]
        lot   = LOT_SIZES.get(name, 1)

        for tf in timeframes:
            try:
                candles     = client.fetch_historical_candles(key, tf_map[tf], days=5)
                htf_candles = client.fetch_historical_candles(key, "30minute", days=10)
            except Exception as e:
                print(f"\n  [ERROR] {name} {tf}: {e}")
                continue

            result = engine.evaluate(candles, htf_candles=htf_candles)
            if "error" in result:
                continue

            signals = result.get("signals", [])

            # Filter to Sep 18 only
            today_sigs = [
                s for s in signals
                if datetime.fromtimestamp(s["time"], tz=IST).strftime("%Y-%m-%d") == SEP18
            ]

            if not today_sigs:
                continue

            print(f"\n{'─'*72}")
            print(f"  {name}  [{tf}]  (1 lot = {lot} qty)")
            print(f"{'─'*72}")

            for s in today_sigs:
                direction = s["signal"]
                entry     = s["entry_price"]
                sl        = s["sl_price"]
                tp        = s["tp_price"]
                model     = s.get("model", "--")
                tier      = s.get("tier", "--")
                sig_bar   = s["bar_index"]
                sig_time  = ts_ist(s["time"])

                outcome, bars_held, hit_price = check_outcome(s, candles, sig_bar)
                pts   = pnl_points(outcome, entry, hit_price, direction)
                money = round(pts * lot * LOTS_TRADED, 2)

                emoji = "✅" if outcome == "TP" else "❌" if outcome == "SL" else "🔵"
                risk_pts  = round(abs(entry - sl), 2)
                rward_pts = round(abs(tp - entry), 2)

                print(f"\n  {emoji} {direction}  @ {sig_time}  |  Model: {model}  |  Tier: {tier}")
                print(f"     Entry   : {entry}")
                print(f"     SL      : {sl}    (Risk:  {risk_pts} pts)")
                print(f"     TP      : {tp}    (Reward:{rward_pts} pts)")
                print(f"     Outcome : {outcome}  in {bars_held} bar(s)  →  Hit @ {hit_price}")
                print(f"     P&L     : {'+' if money >= 0 else ''}{money} ₹  ({'+' if pts >= 0 else ''}{pts} pts × {lot} qty)")

                trades.append({
                    "name": name, "tf": tf, "direction": direction,
                    "entry": entry, "sl": sl, "tp": tp,
                    "outcome": outcome, "pts": pts, "money": money,
                    "model": model, "lot": lot
                })

    # ── Silver Bullet Events ──────────────────────────────────────────────
    print(f"\n{'─'*72}")
    print("  SILVER BULLET EVENT SUMMARY")
    print(f"{'─'*72}")
    print("  (Silver Bullet events track setup stages — TP/SL/TIME_BOXED exits)")

    for inst in all_instruments:
        name = inst["name"]
        key  = inst["instrument_key"]
        lot  = LOT_SIZES.get(name, 1)

        for tf in timeframes:
            try:
                candles     = client.fetch_historical_candles(key, tf_map[tf], days=5)
                htf_candles = client.fetch_historical_candles(key, "30minute", days=10)
            except:
                continue

            result = engine.evaluate(candles, htf_candles=htf_candles)
            if "error" in result:
                continue

            sb_events = result.get("silver_bullet_events", [])
            today_sb  = [
                e for e in sb_events
                if datetime.fromtimestamp(e.get("time", 0), tz=IST).strftime("%Y-%m-%d") == SEP18
            ]

            if not today_sb:
                continue

            # Group into trade sequences (ENTRY → TP/SL/TIME_BOXED)
            sb_entry = None
            for ev in today_sb:
                etype = ev.get("type", "?")
                etime = ts_ist(ev.get("time", 0))
                price = ev.get("price", "?")

                if "ENTRY" in etype or "BUY" in etype or "SELL" in etype:
                    sb_entry = ev
                    print(f"\n  🔵 [{name} {tf}] SB ENTRY  @ {etime}  Price: {price}")
                elif etype == "TP_HIT" and sb_entry:
                    ep = sb_entry.get("price", price)
                    pts = round(abs(float(price) - float(ep)), 2) if ep != "?" else "?"
                    money = round(pts * lot, 2) if pts != "?" else "?"
                    print(f"  ✅ [{name} {tf}] SB TP HIT @ {etime}  Price: {price}  →  +{pts} pts  (+₹{money})")
                    sb_entry = None
                elif etype == "SL_HIT" and sb_entry:
                    ep = sb_entry.get("price", price)
                    pts = round(abs(float(price) - float(ep)), 2) if ep != "?" else "?"
                    money = round(pts * lot, 2) if pts != "?" else "?"
                    print(f"  ❌ [{name} {tf}] SB SL HIT @ {etime}  Price: {price}  →  -{pts} pts  (-₹{money})")
                    sb_entry = None
                elif etype == "TIME_BOXED_EXIT":
                    print(f"  ⏱  [{name} {tf}] SB TIME EXIT @ {etime}  Close: {price}")
                    sb_entry = None
                else:
                    print(f"  ·  [{name} {tf}] {etype} @ {etime}  Price: {price}")

    # ── Grand Summary ─────────────────────────────────────────────────────
    print(f"\n{'='*72}")
    print("  GRAND P&L SUMMARY — Sep 18")
    print(f"{'='*72}")

    if not trades:
        print("  No confirmed signal trades found for Sep 18.")
    else:
        wins   = [t for t in trades if t["outcome"] == "TP"]
        losses = [t for t in trades if t["outcome"] == "SL"]
        opens  = [t for t in trades if t["outcome"] == "OPEN"]

        gross_pnl = sum(t["money"] for t in trades)

        print(f"  Total Trades : {len(trades)}")
        print(f"  Winners (TP) : {len(wins)}")
        print(f"  Losers  (SL) : {len(losses)}")
        print(f"  Still Open   : {len(opens)}")
        if len(trades) > 0:
            wr = len(wins) / (len(wins) + len(losses)) * 100 if (wins or losses) else 0
            print(f"  Win Rate     : {wr:.0f}%")
        print(f"\n  Gross P&L    : {'+'if gross_pnl>=0 else ''}{gross_pnl:.2f} ₹")
        print()
        print("  Per-trade breakdown:")
        for t in trades:
            emoji = "✅" if t["outcome"]=="TP" else "❌" if t["outcome"]=="SL" else "🔵"
            m = t["money"]
            print(f"    {emoji} {t['name']:25s} [{t['tf']}]  {t['direction']}  {t['outcome']}  {'+' if m>=0 else ''}{m:.0f} ₹")

    print(f"\n  NOTE: 1 lot assumed per signal. Adjust LOTS_TRADED in script for actual sizing.")
    print(f"{'='*72}\n")


if __name__ == "__main__":
    main()
