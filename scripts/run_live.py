"""
ICT Live Runner — Main execution loop.
Polls Upstox every 5 minutes, runs ICT engine, and executes
paper/live options orders via Zerodha Kite.

Usage:
    python scripts/run_live.py

Schedule (IST):
    08:50  →  Run scripts/kite_login.py first to refresh token
    09:18  →  Start this script
    09:20  →  Killzone 1 opens, signals eligible
    10:30  →  Killzone 1 closes
    13:30  →  Killzone 2 opens
    15:00  →  Killzone 2 closes
    15:15  →  Auto square-off all positions
    15:30  →  Daily P&L summary via Telegram
"""
import os
import sys
import time
import logging
import yaml
from datetime import datetime
import zoneinfo

# Project root on path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, ".env"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            os.path.join(BASE_DIR, "logs",
                         f"live_{datetime.now().strftime('%Y-%m-%d')}.log")
        )
    ]
)
logger = logging.getLogger("LiveRunner")
IST = zoneinfo.ZoneInfo("Asia/Kolkata")

from src.indicator.engine import ICTPredictiveEngine
from src.data.upstox_client import UpstoxClient
from src.execution.signal_executor import SignalExecutor
from src.alerts.telegram import TelegramNotifier


def load_yaml(filename):
    with open(os.path.join(BASE_DIR, "config", filename)) as f:
        return yaml.safe_load(f) or {}


def ist_now():
    return datetime.now(tz=IST)


def ist_time_str():
    return ist_now().strftime("%H:%M:%S IST")


def is_past(h, m):
    now = ist_now()
    return (now.hour, now.minute) >= (h, m)


def send_daily_summary(executor: SignalExecutor, notifier: TelegramNotifier):
    status = executor.status()
    pnl    = status.get("daily_pnl_inr", 0)
    trades = status.get("open_trades", {})

    msg = (
        f"📊 *ICT Engine — Daily Summary*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Date     : {ist_now().strftime('%d %b %Y')}\n"
        f"Mode     : {'📝 Paper' if status.get('paper_mode') else '🔴 Live'}\n"
        f"P&L      : {'✅' if pnl >= 0 else '❌'} ₹{pnl:+,.0f}\n"
        f"Limit    : ₹{status.get('loss_limit_inr', 2000):,.0f}\n"
        f"Open Pos : {status.get('open_positions', 0)}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Check logs for full trade breakdown."
    )
    try:
        notifier.send_message(msg)
    except Exception as e:
        logger.error(f"Telegram summary failed: {e}")


def main():
    # ── Startup ───────────────────────────────────────────────────────────────
    os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)

    settings_cfg  = load_yaml("settings.yaml")
    instruments   = load_yaml("instruments.yaml")

    engine    = ICTPredictiveEngine(settings_cfg)
    client    = UpstoxClient()
    notifier  = TelegramNotifier()
    executor  = SignalExecutor(config=settings_cfg, notifier=notifier)

    paper_tag = "📝 PAPER MODE" if executor.trader.paper_mode else "🔴 LIVE MODE"
    logger.info("=" * 60)
    logger.info(f"  ICT Live Runner starting — {paper_tag}")
    logger.info(f"  Time: {ist_time_str()}")
    logger.info(f"  Daily loss limit: ₹{executor.gate.max_daily_loss_inr:.0f}")
    logger.info("=" * 60)

    # Enabled instruments
    all_instruments = [
        i for i in instruments.get("indices", []) + instruments.get("stocks", [])
        if i.get("enabled")
    ]

    tf_map = {"5m": "5minute", "15m": "15minute"}
    timeframes = ["5m", "15m"]

    squareoff_done   = False
    summary_done     = False
    poll_interval_s  = 300   # 5 minutes

    # ── Main polling loop ─────────────────────────────────────────────────────
    logger.info("Entering main loop. Press Ctrl+C to stop.")

    while True:
        try:
            now = ist_now()
            now_h, now_m = now.hour, now.minute

            # ── 15:15 — Auto square-off ──────────────────────────────────────
            if (now_h, now_m) >= (15, 15) and not squareoff_done:
                logger.info("⏰ 15:15 — Auto square-off triggered")
                closed = executor.squareoff_all()
                logger.info(f"Squared off {len(closed)} position(s)")
                squareoff_done = True

            # ── 15:30 — Daily summary ─────────────────────────────────────────
            if (now_h, now_m) >= (15, 30) and not summary_done:
                send_daily_summary(executor, notifier)
                summary_done = True
                logger.info("Daily P&L summary sent to Telegram")

            # ── Outside trading hours — skip polling ─────────────────────────
            if not ((9, 15) <= (now_h, now_m) <= (15, 30)):
                logger.info(f"Outside market hours ({now.strftime('%H:%M')} IST) — sleeping 60s")
                time.sleep(60)
                continue

            # ── Kill switch — daily loss hit ─────────────────────────────────
            if executor.gate.status()["kill_switch_hit"]:
                logger.warning("🛑 Daily loss limit hit — no new signals accepted today")
                time.sleep(60)
                continue

            # ── Poll each instrument ─────────────────────────────────────────
            logger.info(f"─── Poll @ {ist_time_str()} ───")

            for inst in all_instruments:
                name = inst["name"]
                key  = inst["instrument_key"]

                try:
                    htf_candles = client.fetch_historical_candles(
                        key, interval="30minute", days=10
                    )
                except Exception as e:
                    logger.error(f"HTF fetch failed for {name}: {e}")
                    continue

                for tf in timeframes:
                    try:
                        candles = client.fetch_historical_candles(
                            key, tf_map[tf], days=7
                        )
                        if not candles:
                            continue

                        # ── Human-like ICT Position Management on latest candle ────
                        executor.update_open_positions(name, candles[-1])

                        result = engine.evaluate(candles, htf_candles=htf_candles)

                        if "error" in result:
                            continue

                        last_bar_idx = len(candles) - 1

                        # ── Process ICT Predictive signals ────────────────────────
                        signals = result.get("signals", [])
                        if signals:
                            latest_sig = signals[-1]
                            sig_dir    = latest_sig.get("signal")
                            sig_bar_idx = latest_sig.get("bar_index", -999)
                            is_fresh   = sig_bar_idx >= last_bar_idx - 2

                            if is_fresh and sig_dir in ("BUY", "SELL"):
                                logger.info(
                                    f"🎯 SIGNAL: {name} [{tf}] {sig_dir} "
                                    f"@ {latest_sig.get('entry_price')} "
                                    f"| Model: {latest_sig.get('model','--')}"
                                )
                                exec_result = executor.process(latest_sig, name, lots=1)
                                if exec_result["executed"]:
                                    logger.info(
                                        f"  → {exec_result['symbol']} "
                                        f"× {exec_result.get('qty')} qty executed"
                                    )
                                else:
                                    logger.info(f"  → Skipped: {exec_result['reason']}")

                        # ── Process Silver Bullet entries ─────────────────────────
                        for sb_ev in result.get("silver_bullet_events", []):
                            ev_type = sb_ev.get("type", "")
                            if "ENTRY" in ev_type:
                                sb_bar = sb_ev.get("bar_index", -999)
                                if sb_bar >= last_bar_idx - 2:
                                    sb_sig = {
                                        "signal":      "BUY" if "BUY" in ev_type else "SELL",
                                        "entry_price": sb_ev.get("price", 0),
                                        "sl_price":    sb_ev.get("sl", 0),
                                        "tp_price":    sb_ev.get("tp", 0),
                                        "model":       "Silver Bullet Model",
                                        "bar_index":   sb_bar,
                                        "time":        sb_ev.get("time", 0),
                                    }
                                    executor.process(sb_sig, name, lots=1)

                    except Exception as e:
                        logger.error(f"Error processing {name} [{tf}]: {e}", exc_info=True)

            # ── Sleep until next poll ─────────────────────────────────────────
            logger.info(f"Next poll in {poll_interval_s//60} min")
            time.sleep(poll_interval_s)

        except KeyboardInterrupt:
            logger.info("\n\nKeyboard interrupt — shutting down cleanly")
            logger.info("Squaring off any remaining positions...")
            executor.squareoff_all()
            send_daily_summary(executor, notifier)
            break
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
            time.sleep(60)


if __name__ == "__main__":
    main()
