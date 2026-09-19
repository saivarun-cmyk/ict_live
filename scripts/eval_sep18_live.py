"""
Sep 18 Signal Evaluation Script
Runs the ICT Predictive Engine on today's data and prints a clean report.
"""
import sys
import os
import json
from datetime import datetime
import zoneinfo

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml
from src.indicator.engine import ICTPredictiveEngine
from src.data.upstox_client import UpstoxClient

IST = zoneinfo.ZoneInfo("Asia/Kolkata")

def load_yaml(path):
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}

def ts_to_ist(ts):
    return datetime.fromtimestamp(ts, tz=IST).strftime("%H:%M  %d-%b-%Y")

def main():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = load_yaml(os.path.join(base, "config", "settings.yaml"))
    instruments_cfg = load_yaml(os.path.join(base, "config", "instruments.yaml"))

    engine = ICTPredictiveEngine(cfg)
    client = UpstoxClient()

    # Collect all enabled instruments
    all_instruments = []
    for item in instruments_cfg.get("indices", []):
        if item.get("enabled"):
            all_instruments.append(item)
    for item in instruments_cfg.get("stocks", []):
        if item.get("enabled"):
            all_instruments.append(item)

    timeframes = ["5m", "15m"]

    sep18_date = "2026-09-18"

    print("=" * 72)
    print(f"  ICT PREDICTIVE ENGINE — Sep 18 Signal Report")
    print(f"  Generated: {datetime.now(tz=IST).strftime('%H:%M  %d-%b-%Y IST')}")
    print("=" * 72)

    total_signals = 0
    total_sb = 0

    for inst in all_instruments:
        name = inst["name"]
        key  = inst["instrument_key"]

        for tf in timeframes:
            tf_map = {"5m": "5minute", "15m": "15minute"}
            interval = tf_map.get(tf, "5minute")

            try:
                candles = client.fetch_historical_candles(key, interval=interval, days=5)
                htf_candles = client.fetch_historical_candles(key, interval="30minute", days=10)
            except Exception as e:
                print(f"\n[ERROR] {name} {tf}: {e}")
                continue

            # Filter to today only
            today_candles = [
                c for c in candles
                if datetime.fromtimestamp(c.timestamp, tz=IST).strftime("%Y-%m-%d") == sep18_date
            ]

            if not today_candles:
                print(f"\n  {name} [{tf}] — No candles for Sep 18 (market closed or data unavailable)")
                continue

            result = engine.evaluate(candles, htf_candles=htf_candles)

            if "error" in result:
                print(f"\n  {name} [{tf}] — Engine error: {result['error']}")
                continue

            signals     = result.get("signals", [])
            sb_events   = result.get("silver_bullet_events", [])
            htf_bias    = result.get("htf_bias", "NEUTRAL")
            final_sig   = result.get("signal", "HOLD")
            dashboard   = result.get("dashboard", {})

            # Filter signals to today
            today_signals = [
                s for s in signals
                if datetime.fromtimestamp(s["time"], tz=IST).strftime("%Y-%m-%d") == sep18_date
            ]
            today_sb = [
                s for s in sb_events
                if datetime.fromtimestamp(s.get("time", 0), tz=IST).strftime("%Y-%m-%d") == sep18_date
            ]

            total_signals += len(today_signals)
            total_sb      += len(today_sb)

            print(f"\n{'─'*72}")
            print(f"  {name}  [{tf}]   HTF Bias: {htf_bias}   Final State: {final_sig}")
            print(f"{'─'*72}")

            if not today_signals and not today_sb:
                print("  No signals generated today.")
            else:
                for s in today_signals:
                    direction = s.get("direction", "?")
                    time_str  = ts_to_ist(s["time"])
                    entry     = s.get("entry_price",  s.get("entry", "?"))
                    sl        = s.get("sl_price",     s.get("sl", "?"))
                    tp        = s.get("tp_price",     s.get("tp", "?"))
                    model     = s.get("entry_model",  s.get("model", "--"))
                    zone_type = s.get("zone_type",    "")
                    tier      = s.get("tier",         "")
                    in_kz     = s.get("in_killzone",  s.get("killzone", False))
                    cisd      = s.get("cisd_state",   "")
                    bias_st   = s.get("bias_state",   "")

                    kz_tag = "✅ KZ" if in_kz else "⚠️ OOK"  # OOK = Out of Killzone

                    # Compute R:R
                    try:
                        rr = abs(float(tp) - float(entry)) / abs(float(entry) - float(sl))
                        rr_str = f"{rr:.1f}R"
                    except:
                        rr_str = "?"

                    print(f"\n  [{direction}]  {time_str}  {kz_tag}")
                    print(f"    Model      : {model}")
                    print(f"    Zone       : {zone_type} | Tier: {tier}")
                    print(f"    Entry      : {entry}")
                    print(f"    Stop Loss  : {sl}")
                    print(f"    Take Profit: {tp}  ({rr_str})")
                    print(f"    CISD State : {cisd}   Bias: {bias_st}")

                for sb in today_sb:
                    time_str = ts_to_ist(sb.get("time", 0))
                    print(f"\n  [SILVER BULLET]  {time_str}")
                    print(f"    Direction  : {sb.get('direction','?')}")
                    print(f"    Entry      : {sb.get('entry','?')}")
                    print(f"    SL         : {sb.get('sl','?')}")
                    print(f"    TP         : {sb.get('tp','?')}")
                    print(f"    State      : {sb.get('state','?')}")

    print(f"\n{'='*72}")
    print(f"  SUMMARY  |  Signals: {total_signals}  |  Silver Bullets: {total_sb}")
    print(f"{'='*72}\n")

    # ---- Config audit ----
    print("CONFIG AUDIT (active settings):")
    print(f"  use_killzone   : {cfg.get('killzones',{}).get('use_killzone')}")
    print(f"  killzone1      : {cfg.get('killzones',{}).get('killzone1')}")
    print(f"  killzone2      : {cfg.get('killzones',{}).get('killzone2')}")
    print(f"  use_htf_bias   : {cfg.get('htf_bias',{}).get('use_htf_bias')}  ← currently OFF")
    print(f"  htf_bias_strict: {cfg.get('htf_bias',{}).get('htf_bias_strict')}  ← currently OFF")
    print(f"  min_fvg_tier   : {cfg.get('fvg_quality',{}).get('min_fvg_tier')}")
    print(f"  risk_reward    : {cfg.get('risk',{}).get('risk_reward')}")
    print(f"  use_silver_bul : {cfg.get('silver_bullet',{}).get('use_silver_bullet')}")
    print(f"  use_cisd       : {cfg.get('cisd',{}).get('use_cisd')}")
    print()

if __name__ == "__main__":
    main()
