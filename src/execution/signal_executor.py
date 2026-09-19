"""
Signal Executor — Bridges ICT engine signals to Kite order placement.
This is the main glue layer: engine signal dict → RiskGate → KiteTrader.
"""
import os
import logging
import yaml
from datetime import datetime
from typing import Dict, Any, Optional, List
import zoneinfo

from .risk_gate import RiskGate
from .kite_trader import KiteTrader
from src.alerts.telegram import TelegramNotifier

IST = zoneinfo.ZoneInfo("Asia/Kolkata")
logger = logging.getLogger("SignalExecutor")


class SignalExecutor:
    def __init__(self, config: Optional[Dict[str, Any]] = None, notifier: Optional[TelegramNotifier] = None):
        self.config   = config or self._load_config()
        self.gate     = RiskGate(self.config)
        self.trader   = KiteTrader(self.config)
        self.notifier = notifier or TelegramNotifier()
        self.trader.start_monitoring()

        mode = "📝 PAPER" if self.trader.paper_mode else "🔴 LIVE"
        logger.info(f"SignalExecutor ready — {mode} | "
                    f"Daily loss limit: ₹{self.gate.max_daily_loss_inr:.0f}")

    def _load_config(self) -> Dict[str, Any]:
        try:
            base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            cfg_path = os.path.join(base, "config", "settings.yaml")
            if os.path.exists(cfg_path):
                with open(cfg_path) as f:
                    return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"SignalExecutor could not load settings.yaml: {e}")
        return {}

    def update_open_positions(self, instrument_name: str, latest_candle: Any) -> List[Dict[str, Any]]:
        """
        Human-like ICT Desk Trader: Active Candle Evaluation.
        Checks open trades for `instrument_name` against the current candle bar.
        Handles:
          - Moving Stop Loss to Breakeven at +1.0R (Risk = 0)
          - Proximity Profit Locking (85-90% of TP with stall/wick rejection)
          - Full TP hits and SL / Breakeven hits
        Syncs state with RiskGate and dispatches Telegram notifications.
        """
        events = self.trader.check_trades_with_candle(
            instrument_name, latest_candle, notifier=self.notifier
        )

        for ev in events:
            ev_type = ev.get("event")
            trade_id = ev.get("trade_id")
            if ev_type == "TRADE_CLOSED":
                pnl = ev.get("pnl", 0.0)
                self.gate.close_position(trade_id, pnl_inr=pnl)
                logger.info(f"SignalExecutor: Closed {trade_id} synced with RiskGate | Realized P&L ₹{pnl:+,.0f}")
            elif ev_type == "BREAKEVEN_MOVED":
                self.gate.mark_breakeven(trade_id)
                logger.info(f"SignalExecutor: {trade_id} marked as risk-free at BE in RiskGate")

        return events

    def process(
        self,
        signal: Dict[str, Any],
        instrument_name: str,
        lots: int = 1
    ) -> Dict[str, Any]:
        """
        Main entry point. Call this for every signal the engine emits.

        Returns a result dict:
          { "executed": bool, "reason": str, "trade_id": str|None,
            "symbol": str|None, "strike": int|None }
        """
        direction  = signal.get("signal", "?")
        entry      = signal.get("entry_price", 0)
        sl         = signal.get("sl_price", 0)
        tp         = signal.get("tp_price", 0)
        model      = signal.get("model", "--")
        bar_time   = signal.get("time", 0)
        bar_dt     = datetime.fromtimestamp(bar_time, tz=IST).strftime("%H:%M") if bar_time else "--"

        # Attach instrument name to signal for dedup key
        signal = {**signal, "instrument": instrument_name}

        grade = signal.get("grade", "")
        score = signal.get("confluence_score", 0)
        score_str = f" | Grade: {grade} ({score}/100)" if score > 0 else ""

        logger.info(
            f"Signal received: {instrument_name} {direction} @ {entry} "
            f"| SL {sl} | TP {tp} | Model: {model}{score_str} | Bar: {bar_dt}"
        )

        # Find any existing trade for pyramiding notification context
        existing_trades = [
            t for t in self.trader.get_open_trades().values()
            if t.get("instrument") == instrument_name
        ]

        # ── 1. Risk Gate check ───────────────────────────────────────────────
        allowed, reason = self.gate.is_allowed(signal)
        if not allowed:
            logger.warning(f"  ⛔ Blocked by RiskGate: {reason}")
            return {"executed": False, "reason": reason, "trade_id": None,
                    "symbol": None, "strike": None}

        # ── 2. Register signal (dedup) ────────────────────────────────────────
        self.gate.register_signal(signal)

        # ── 3. Get option details ─────────────────────────────────────────────
        ts, exchange, lot_size, strike = self.trader.get_option_details(
            instrument_name, direction, entry
        )
        if ts is None:
            reason = f"{instrument_name} not configured for options execution"
            logger.warning(f"  ⛔ {reason}")
            return {"executed": False, "reason": reason, "trade_id": None,
                    "symbol": None, "strike": None}

        # ── 4. Place order ────────────────────────────────────────────────────
        trade_id = self.trader.place_order(signal, instrument_name, lots=lots)
        if trade_id is None:
            reason = "Order placement failed (check logs)"
            return {"executed": False, "reason": reason, "trade_id": None,
                    "symbol": ts, "strike": strike}

        # ── 5. Register open position in risk gate ────────────────────────────
        self.gate.open_position(trade_id, {
            "instrument": instrument_name,
            "direction":  direction,
            "entry":      entry,
            "sl":         sl,
            "tp":         tp,
            "symbol":     ts,
            "strike":     strike,
            "lots":       lots
        })

        # ── 6. Desk Alert Dispatch ────────────────────────────────────────────
        if signal.get("is_pyramid") and existing_trades:
            self.notifier.notify_pyramid(instrument_name, existing_trades[0], signal)
        else:
            self.notifier.notify_signal(instrument_name, signal)

        mode_tag = "[PAPER]" if self.trader.paper_mode else "[LIVE]"
        logger.info(
            f"  ✅ {mode_tag} Order placed: {ts} × {lot_size * lots} qty "
            f"| Strike {strike} | trade_id: {trade_id}"
        )

        return {
            "executed": True,
            "reason":   "ok",
            "trade_id": trade_id,
            "symbol":   ts,
            "strike":   strike,
            "exchange": exchange,
            "qty":      lot_size * lots,
        }

    def process_result(
        self,
        engine_result: Dict[str, Any],
        instrument_name: str,
        lots: int = 1
    ) -> list:
        """
        Convenience method: pass the full engine.evaluate() result dict.
        Processes all signals and silver bullet entries from a single evaluation.
        Returns list of execution results.
        """
        executed = []

        for sig in engine_result.get("signals", []):
            if sig.get("signal") in ("BUY", "SELL"):
                result = self.process(sig, instrument_name, lots)
                executed.append(result)

        # Silver Bullet entries (type contains ENTRY or BUY/SELL)
        for ev in engine_result.get("silver_bullet_events", []):
            ev_type = ev.get("type", "")
            if "ENTRY" in ev_type:
                # Wrap SB event as a signal dict
                fake_sig = {
                    "signal":      "BUY" if "BUY" in ev_type else "SELL",
                    "entry_price": ev.get("price", 0),
                    "sl_price":    ev.get("sl", 0),
                    "tp_price":    ev.get("tp", 0),
                    "model":       "Silver Bullet Model",
                    "bar_index":   ev.get("bar_index", 0),
                    "time":        ev.get("time", 0),
                }
                result = self.process(fake_sig, instrument_name, lots)
                executed.append(result)

        return executed

    def squareoff_all(self) -> list:
        """Force close all positions — call at 15:15 IST."""
        closed = self.trader.square_off_all("15:15 auto square-off")
        for trade_id in closed:
            self.gate.close_position(trade_id, pnl_inr=0.0)  # P&L updated by monitor
        return closed

    def status(self) -> Dict[str, Any]:
        """Returns full engine status for dashboard/Telegram."""
        gate_status = self.gate.status()
        return {
            **gate_status,
            "paper_mode":    self.trader.paper_mode,
            "open_trades":   self.trader.get_open_trades(),
        }
