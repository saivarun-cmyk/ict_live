"""
Risk Gate — Safety layer between signal and order placement.
Every signal passes through here before execution.
"""
import os
import json
import logging
import yaml
from datetime import datetime, time
from typing import Dict, Any, Optional, Tuple
import zoneinfo

IST = zoneinfo.ZoneInfo("Asia/Kolkata")
logger = logging.getLogger("RiskGate")


class RiskGate:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or self._load_config()
        self.trade_mgmt = self.config.get("trade_management", {})
        self.allow_pyramiding = self.trade_mgmt.get("allow_pyramiding_if_risk_free", True)

        self.max_daily_loss_inr   = float(os.getenv("DAILY_LOSS_LIMIT_INR", "2000"))
        self.max_open_positions   = int(self.config.get("risk", {}).get("max_open_positions", 2))
        self.allowed_start        = time(9, 20)    # 09:20 IST
        self.allowed_end          = time(15, 15)   # 15:15 IST
        self.squareoff_deadline   = time(15, 15)

        # In-memory state (reset each day)
        self._daily_realized_pnl  = 0.0
        self._open_positions: Dict[str, Dict] = {}   # key = trade_id
        self._recent_signal_ids   = set()            # dedup guard

        self._load_daily_state()

    def _load_config(self) -> Dict[str, Any]:
        try:
            base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            cfg_path = os.path.join(base, "config", "settings.yaml")
            if os.path.exists(cfg_path):
                with open(cfg_path) as f:
                    return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"RiskGate could not load settings.yaml: {e}")
        return {}

    # ── State persistence ─────────────────────────────────────────────────────

    def _state_file(self) -> str:
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        log_dir = os.path.join(base, "logs")
        os.makedirs(log_dir, exist_ok=True)
        today = datetime.now(tz=IST).strftime("%Y-%m-%d")
        return os.path.join(log_dir, f"daily_state_{today}.json")

    def _load_daily_state(self):
        f = self._state_file()
        if os.path.exists(f):
            try:
                with open(f) as fh:
                    data = json.load(fh)
                self._daily_realized_pnl  = data.get("realized_pnl", 0.0)
                self._open_positions      = data.get("open_positions", {})
                self._recent_signal_ids   = set(data.get("signal_ids", []))
                logger.info(f"RiskGate: loaded state — realized P&L ₹{self._daily_realized_pnl}, "
                            f"{len(self._open_positions)} open position(s)")
            except Exception as e:
                logger.warning(f"RiskGate: could not load state: {e}")

    def _save_daily_state(self):
        f = self._state_file()
        with open(f, "w") as fh:
            json.dump({
                "realized_pnl":   self._daily_realized_pnl,
                "open_positions": self._open_positions,
                "signal_ids":     list(self._recent_signal_ids)
            }, fh, indent=2)

    # ── Main gate ─────────────────────────────────────────────────────────────

    def is_allowed(self, signal: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Returns (True, "ok") if signal can be executed,
        or (False, "reason") if blocked.
        """
        now = datetime.now(tz=IST)
        now_time = now.time()

        # 1. Market hours check
        if not (self.allowed_start <= now_time <= self.allowed_end):
            return False, f"Outside trading hours ({now_time.strftime('%H:%M')} IST)"

        # 2. Daily loss kill-switch
        if self._daily_realized_pnl <= -self.max_daily_loss_inr:
            return False, (f"Daily loss limit hit ₹{abs(self._daily_realized_pnl):.0f} "
                           f"≥ ₹{self.max_daily_loss_inr:.0f} — bot stopped for today")

        # 3. Max open positions
        if len(self._open_positions) >= self.max_open_positions:
            return False, (f"Max open positions reached ({len(self._open_positions)}"
                           f"/{self.max_open_positions})")

        # 4. Same instrument exposure & Pyramiding checks
        inst = signal.get("instrument")
        sig_dir = signal.get("signal")
        existing_inst_trades = [t for t in self._open_positions.values() if t.get("instrument") == inst]
        if existing_inst_trades:
            for et in existing_inst_trades:
                if et.get("direction") != sig_dir:
                    return False, f"Conflicting open position on {inst} ({et.get('direction')} vs {sig_dir})"
                if self.allow_pyramiding:
                    if not et.get("breakeven_moved", False):
                        return False, (f"Existing {inst} {sig_dir} trade not yet risk-free at Breakeven. "
                                       f"Pyramiding blocked to protect capital.")
                    else:
                        logger.info(f"RiskGate: Allowing pyramid entry for {inst} — primary trade is risk-free at BE.")
                        signal["is_pyramid"] = True
                else:
                    return False, f"Position already open on {inst} and pyramiding is disabled"

        # 5. Duplicate signal guard
        sig_id = self._make_signal_id(signal)
        if sig_id in self._recent_signal_ids:
            return False, f"Duplicate signal suppressed: {sig_id}"

        # 6. Square-off time — no new entries after 15:15
        if now_time >= self.squareoff_deadline:
            return False, "Past square-off deadline (15:15 IST) — no new entries"

        return True, "ok"

    # ── Position tracking ────────────────────────────────────────────────────

    def register_signal(self, signal: Dict[str, Any]):
        """Call this after is_allowed() returns True, before placing order."""
        sig_id = self._make_signal_id(signal)
        self._recent_signal_ids.add(sig_id)
        self._save_daily_state()

    def open_position(self, trade_id: str, trade: Dict[str, Any]):
        """Called when an order is confirmed placed."""
        self._open_positions[trade_id] = {
            **trade,
            "breakeven_moved": trade.get("breakeven_moved", False)
        }
        self._save_daily_state()
        logger.info(f"RiskGate: opened position {trade_id}")

    def mark_breakeven(self, trade_id: str):
        """Mark trade as risk-free at Breakeven, opening pyramiding eligibility."""
        if trade_id in self._open_positions:
            self._open_positions[trade_id]["breakeven_moved"] = True
            self._save_daily_state()
            logger.info(f"RiskGate: {trade_id} marked as risk-free at Breakeven")

    def close_position(self, trade_id: str, pnl_inr: float):
        """Called when a position is closed (TP/SL/time exit)."""
        if trade_id in self._open_positions:
            del self._open_positions[trade_id]
        self._daily_realized_pnl += pnl_inr
        self._save_daily_state()
        logger.info(f"RiskGate: closed {trade_id} | P&L ₹{pnl_inr:+.0f} | "
                    f"Daily: ₹{self._daily_realized_pnl:+.0f}")

    def should_squareoff(self) -> bool:
        """Returns True if it's time to force-close all positions."""
        now_time = datetime.now(tz=IST).time()
        return now_time >= self.squareoff_deadline

    # ── Status ───────────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        return {
            "daily_pnl_inr":    self._daily_realized_pnl,
            "loss_limit_inr":   self.max_daily_loss_inr,
            "limit_remaining":  self.max_daily_loss_inr + self._daily_realized_pnl,
            "open_positions":   len(self._open_positions),
            "kill_switch_hit":  self._daily_realized_pnl <= -self.max_daily_loss_inr,
        }

    # ── Internal ─────────────────────────────────────────────────────────────

    @staticmethod
    def _make_signal_id(signal: Dict[str, Any]) -> str:
        """Creates a unique ID for a signal to prevent double-entry."""
        bar = signal.get("bar_index", 0)
        sig = signal.get("signal", "?")
        entry = signal.get("entry_price", 0)
        inst = signal.get("instrument", "X")
        return f"{inst}_{sig}_{entry}_{bar}"
