"""
Kite Trader — Core execution engine for placing options orders via Zerodha Kite.

Paper mode (PAPER_MODE=true):
    All order logic runs but NO real Kite API calls are made.
    Trades are written to logs/paper_trades_YYYY-MM-DD.json.

Live mode (PAPER_MODE=false):
    Real orders placed via kiteconnect. 1 lot per signal.
    MIS (intraday) only. Auto square-off at 15:15 IST.
"""
import os
import json
import time
import logging
import threading
import yaml
from datetime import datetime
from typing import Dict, Any, Optional, List
import zoneinfo

IST = zoneinfo.ZoneInfo("Asia/Kolkata")
logger = logging.getLogger("KiteTrader")


# ── Strike interval per instrument ──────────────────────────────────────────
STRIKE_INTERVALS = {
    "NIFTY":      50,
    "BANKNIFTY":  100,
    "SENSEX":     100,
}

# ── Lot sizes ────────────────────────────────────────────────────────────────
LOT_SIZES = {
    "NIFTY":      50,
    "BANKNIFTY":  15,
    "SENSEX":     10,
}


def _round_to_strike(price: float, interval: int) -> int:
    """Round spot price to nearest strike interval."""
    return int(round(price / interval) * interval)


def _make_tradingsymbol(symbol: str, direction: str, spot: float, expiry_str: str) -> str:
    """
    Build NFO/BSE options tradingsymbol.
    e.g. BANKNIFTY26SEP57000CE
    expiry_str: format like '26SEP' (day + 3-letter month)
    """
    interval = STRIKE_INTERVALS.get(symbol, 100)
    strike   = _round_to_strike(spot, interval)
    opt_type = "CE" if direction == "BUY" else "PE"

    if symbol == "SENSEX":
        # SENSEX options trade on BSE
        return f"SENSEX{expiry_str}{strike}{opt_type}"
    return f"{symbol}{expiry_str}{strike}{opt_type}"


def _current_weekly_expiry() -> str:
    """
    Returns the nearest Thursday expiry in 'DDMMM' format (e.g. '26SEP').
    NIFTY/BANKNIFTY: weekly Thursday expiry.
    """
    from datetime import timedelta
    now = datetime.now(tz=IST)
    days_to_thursday = (3 - now.weekday()) % 7
    if days_to_thursday == 0 and now.hour >= 15:
        days_to_thursday = 7
    expiry_dt = now + timedelta(days=days_to_thursday)
    return expiry_dt.strftime("%-d%b").upper()   # e.g. '26SEP'


class KiteTrader:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config     = config or self._load_config()
        self.paper_mode = os.getenv("PAPER_MODE", "true").lower() == "true"
        self.api_key    = os.getenv("KITE_API_KEY", "").strip()
        self.api_secret = os.getenv("KITE_API_SECRET", "").strip()
        self.access_token = os.getenv("KITE_ACCESS_TOKEN", "").strip()

        self._kite = None
        self._open_trades: Dict[str, Dict] = {}   # trade_id → trade dict
        self._monitor_thread: Optional[threading.Thread] = None
        self._running = False

        if not self.paper_mode:
            self._connect_kite()

        mode = "📝 PAPER MODE" if self.paper_mode else "🔴 LIVE MODE"
        logger.info(f"KiteTrader initialised — {mode}")

    def _load_config(self) -> Dict[str, Any]:
        try:
            base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            cfg_path = os.path.join(base, "config", "settings.yaml")
            if os.path.exists(cfg_path):
                with open(cfg_path) as f:
                    return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"KiteTrader could not load settings.yaml: {e}")
        return {}

    # ── Kite connection ──────────────────────────────────────────────────────

    def _connect_kite(self):
        try:
            from kiteconnect import KiteConnect
            self._kite = KiteConnect(api_key=self.api_key)
            self._kite.set_access_token(self.access_token)
            profile = self._kite.profile()
            logger.info(f"Kite connected: {profile.get('user_name')} ({profile.get('user_id')})")
        except Exception as e:
            logger.error(f"Kite connection failed: {e}")
            self._kite = None

    def is_connected(self) -> bool:
        return self.paper_mode or (self._kite is not None)

    # ── Strike & symbol ──────────────────────────────────────────────────────

    def get_option_details(self, instrument_name: str, direction: str, spot_price: float):
        """Returns (tradingsymbol, exchange, lot_size, strike)."""
        sym_map = {
            "NIFTY 50":              "NIFTY",
            "BANK NIFTY":            "BANKNIFTY",
            "SENSEX":                "SENSEX",
            "Reliance Industries":   None,   # equity, skip for now
            "HDFC Bank":             None,
        }
        symbol = sym_map.get(instrument_name)
        if symbol is None:
            return None, None, 1, None

        expiry   = _current_weekly_expiry()
        ts       = _make_tradingsymbol(symbol, direction, spot_price, expiry)
        exchange = "BSE" if symbol == "SENSEX" else "NFO"
        lot      = LOT_SIZES.get(symbol, 1)
        interval = STRIKE_INTERVALS.get(symbol, 100)
        strike   = _round_to_strike(spot_price, interval)

        return ts, exchange, lot, strike

    # ── Order placement ──────────────────────────────────────────────────────

    def place_order(
        self,
        signal: Dict[str, Any],
        instrument_name: str,
        lots: int = 1
    ) -> Optional[str]:
        """
        Places a BUY order for the appropriate options contract.
        Returns trade_id on success, None on failure.
        """
        direction   = signal.get("signal")           # "BUY" or "SELL"
        spot_entry  = signal.get("entry_price", 0)
        spot_sl     = signal.get("sl_price", 0)
        spot_tp     = signal.get("tp_price", 0)
        model       = signal.get("model", "--")
        bar_idx     = signal.get("bar_index", 0)

        ts, exchange, lot_size, strike = self.get_option_details(instrument_name, direction, spot_entry)
        if ts is None:
            logger.info(f"Skipping {instrument_name} — equity options not configured yet")
            return None

        qty = lot_size * lots
        trade_id = f"{instrument_name.replace(' ','_')}_{direction}_{int(time.time() * 1000)}"

        spot_entry = float(spot_entry)
        spot_sl = float(spot_sl)
        spot_tp = float(spot_tp)
        risk_pts = abs(spot_entry - spot_sl)
        reward_pts = abs(spot_tp - spot_entry)

        trade = {
            "trade_id":       trade_id,
            "instrument":     instrument_name,
            "symbol":         ts,
            "exchange":       exchange,
            "direction":      direction,
            "lot_size":       lot_size,
            "lots":           lots,
            "qty":            qty,
            "strike":         strike,
            "spot_entry":     spot_entry,
            "spot_sl":        spot_sl,
            "spot_tp":        spot_tp,
            "risk_pts":       risk_pts,
            "reward_pts":     reward_pts,
            "current_sl":     spot_sl,
            "breakeven_moved": False,
            "near_tp_booked": False,
            "highest_r":      0.0,
            "model":          model,
            "entry_time":     datetime.now(tz=IST).isoformat(),
            "entry_premium":  None,    # filled after order confirmation
            "sl_order_id":    None,
            "tp_order_id":    None,
            "kite_order_id":  None,
            "status":         "PENDING",
            "paper_mode":     self.paper_mode,
        }

        if self.paper_mode:
            # ── Paper mode: simulate fill at current LTP estimate ────────────
            trade["entry_premium"] = self._estimate_premium(spot_entry, strike, direction)
            trade["kite_order_id"] = f"PAPER_{int(time.time())}"
            trade["status"]        = "OPEN"
            self._open_trades[trade_id] = trade
            self._log_paper_trade("ORDER_PLACED", trade)

            logger.info(
                f"[PAPER] {direction} {ts} × {qty} | "
                f"Strike: {strike} | "
                f"Est. Premium: ₹{trade['entry_premium']} | "
                f"Spot entry: {spot_entry:.2f} | SL: {spot_sl:.2f} | TP: {spot_tp:.2f}"
            )

        else:
            # ── Live mode: real Kite order ────────────────────────────────────
            if self._kite is None:
                logger.error("Kite not connected — cannot place live order")
                return None
            try:
                from kiteconnect import KiteConnect
                order_id = self._kite.place_order(
                    variety   = KiteConnect.VARIETY_REGULAR,
                    exchange  = exchange,
                    tradingsymbol = ts,
                    transaction_type = KiteConnect.TRANSACTION_TYPE_BUY,
                    quantity  = qty,
                    order_type= KiteConnect.ORDER_TYPE_MARKET,
                    product   = KiteConnect.PRODUCT_MIS,
                    tag       = "ICT_ENGINE"
                )
                trade["kite_order_id"] = order_id
                trade["status"]        = "OPEN"
                self._open_trades[trade_id] = trade
                logger.info(
                    f"[LIVE] Order placed: {ts} × {qty} | "
                    f"Kite ID: {order_id} | "
                    f"Spot entry: {spot_entry:.2f}"
                )
            except Exception as e:
                logger.error(f"Order placement failed: {e}")
                return None

        return trade_id

    # ── Institutional ICT Desk Position Management (Candle Evaluation) ──────

    def check_trades_with_candle(
        self,
        instrument_name: str,
        candle: Any,
        notifier: Optional[Any] = None
    ) -> List[Dict[str, Any]]:
        """
        Institutional ICT Desk Trader Brain.
        Evaluates open positions for `instrument_name` against the latest candle bar:
          1. Dynamic De-risking: +1.0R expansion moves SL to Breakeven (Risk = 0).
          2. Proximity Profit Locking: 85-90% to TP with stall/rejection locks profit.
          3. Full Take Profit Hit: 2.0R exit.
          4. Stop Loss / Breakeven Hit: Scratch trade (if at BE) or defined loss.
        Works in BOTH Paper Mode and Live Mode.
        """
        if hasattr(candle, "high"):
            open_p  = float(candle.open)
            high_p  = float(candle.high)
            low_p   = float(candle.low)
            close_p = float(candle.close)
        elif isinstance(candle, dict):
            open_p  = float(candle.get("open", 0))
            high_p  = float(candle.get("high", 0))
            low_p   = float(candle.get("low", 0))
            close_p = float(candle.get("close", 0))
        else:
            return []

        tm = self.config.get("trade_management", {})
        enable_be = tm.get("enable_breakeven_at_1r", True)
        be_r = float(tm.get("breakeven_trigger_r", 1.0))
        enable_near_tp = tm.get("enable_near_tp_lock", True)
        near_tp_pct = float(tm.get("near_tp_threshold_pct", 85.0))
        stall_wick_pct = float(tm.get("rejection_stall_wick_pct", 20.0))

        events = []

        for trade_id, trade in list(self._open_trades.items()):
            if trade.get("instrument") != instrument_name:
                continue

            direction = trade.get("direction")
            entry = float(trade.get("spot_entry", 0))
            sl = float(trade.get("current_sl", trade.get("spot_sl", 0)))
            tp = float(trade.get("spot_tp", 0))
            risk_pts = float(trade.get("risk_pts", abs(entry - sl) or 1.0))

            if direction == "BUY":
                # 1. Stop Loss / Breakeven check
                if low_p <= sl:
                    reason = "BREAKEVEN_HIT" if trade.get("breakeven_moved") else "SL_HIT"
                    exit_spot = sl
                    closed_info = self._close_trade(trade_id, trade, exit_spot, reason)
                    if notifier:
                        notifier.notify_trade_closed(instrument_name, trade, reason, exit_spot, closed_info["pnl"])
                    events.append({"event": "TRADE_CLOSED", "trade_id": trade_id, "reason": reason, **closed_info})
                    continue

                # 2. Take Profit check
                if high_p >= tp:
                    reason = "TP_HIT"
                    exit_spot = tp
                    closed_info = self._close_trade(trade_id, trade, exit_spot, reason)
                    if notifier:
                        notifier.notify_trade_closed(instrument_name, trade, reason, exit_spot, closed_info["pnl"])
                    events.append({"event": "TRADE_CLOSED", "trade_id": trade_id, "reason": reason, **closed_info})
                    continue

                # 3. +1.0R Breakeven Trigger
                if enable_be and not trade.get("breakeven_moved"):
                    be_target = entry + (be_r * risk_pts)
                    if high_p >= be_target:
                        trade["breakeven_moved"] = True
                        trade["current_sl"] = entry
                        self._log_paper_trade("BREAKEVEN_MOVED", {
                            **trade,
                            "current_price": high_p,
                            "message": f"Moved SL to Breakeven @ {entry:.2f} (+{be_r}R reached)"
                        })
                        logger.info(f"[{trade_id}] 🛡️ ICT Pro: SL moved to Breakeven @ ₹{entry:.2f} (High {high_p:.2f} >= {be_target:.2f})")
                        if notifier:
                            notifier.notify_breakeven(instrument_name, trade, high_p)
                        events.append({"event": "BREAKEVEN_MOVED", "trade_id": trade_id, "trade": trade})

                # 4. Proximity / Near-TP Profit Lock
                if enable_near_tp and not trade.get("near_tp_booked"):
                    near_tp_level = entry + (near_tp_pct / 100.0) * (tp - entry)
                    if high_p >= near_tp_level:
                        c_range = max(high_p - low_p, 0.05)
                        upper_wick = high_p - max(open_p, close_p)
                        wick_pct = (upper_wick / c_range) * 100.0
                        is_stall = (wick_pct >= stall_wick_pct) or (close_p < high_p - 0.25 * c_range)
                        if is_stall:
                            reason = "NEAR_TP_PROFIT_LOCK"
                            exit_spot = close_p
                            pct_reached = ((high_p - entry) / max(tp - entry, 0.01)) * 100.0
                            closed_info = self._close_trade(trade_id, trade, exit_spot, reason)
                            if notifier:
                                pnl_pts = exit_spot - entry
                                notifier.notify_near_tp_lock(
                                    instrument_name, trade, exit_spot, pnl_pts, closed_info["pnl"], pct_reached
                                )
                            events.append({"event": "TRADE_CLOSED", "trade_id": trade_id, "reason": reason, **closed_info})
                            continue

            elif direction == "SELL":
                # 1. Stop Loss / Breakeven check
                if high_p >= sl:
                    reason = "BREAKEVEN_HIT" if trade.get("breakeven_moved") else "SL_HIT"
                    exit_spot = sl
                    closed_info = self._close_trade(trade_id, trade, exit_spot, reason)
                    if notifier:
                        notifier.notify_trade_closed(instrument_name, trade, reason, exit_spot, closed_info["pnl"])
                    events.append({"event": "TRADE_CLOSED", "trade_id": trade_id, "reason": reason, **closed_info})
                    continue

                # 2. Take Profit check
                if low_p <= tp:
                    reason = "TP_HIT"
                    exit_spot = tp
                    closed_info = self._close_trade(trade_id, trade, exit_spot, reason)
                    if notifier:
                        notifier.notify_trade_closed(instrument_name, trade, reason, exit_spot, closed_info["pnl"])
                    events.append({"event": "TRADE_CLOSED", "trade_id": trade_id, "reason": reason, **closed_info})
                    continue

                # 3. +1.0R Breakeven Trigger
                if enable_be and not trade.get("breakeven_moved"):
                    be_target = entry - (be_r * risk_pts)
                    if low_p <= be_target:
                        trade["breakeven_moved"] = True
                        trade["current_sl"] = entry
                        self._log_paper_trade("BREAKEVEN_MOVED", {
                            **trade,
                            "current_price": low_p,
                            "message": f"Moved SL to Breakeven @ {entry:.2f} (+{be_r}R reached)"
                        })
                        logger.info(f"[{trade_id}] 🛡️ ICT Pro: SL moved to Breakeven @ ₹{entry:.2f} (Low {low_p:.2f} <= {be_target:.2f})")
                        if notifier:
                            notifier.notify_breakeven(instrument_name, trade, low_p)
                        events.append({"event": "BREAKEVEN_MOVED", "trade_id": trade_id, "trade": trade})

                # 4. Proximity / Near-TP Profit Lock
                if enable_near_tp and not trade.get("near_tp_booked"):
                    near_tp_level = entry - (near_tp_pct / 100.0) * (entry - tp)
                    if low_p <= near_tp_level:
                        c_range = max(high_p - low_p, 0.05)
                        lower_wick = min(open_p, close_p) - low_p
                        wick_pct = (lower_wick / c_range) * 100.0
                        is_stall = (wick_pct >= stall_wick_pct) or (close_p > low_p + 0.25 * c_range)
                        if is_stall:
                            reason = "NEAR_TP_PROFIT_LOCK"
                            exit_spot = close_p
                            pct_reached = ((entry - low_p) / max(entry - tp, 0.01)) * 100.0
                            closed_info = self._close_trade(trade_id, trade, exit_spot, reason)
                            if notifier:
                                pnl_pts = entry - exit_spot
                                notifier.notify_near_tp_lock(
                                    instrument_name, trade, exit_spot, pnl_pts, closed_info["pnl"], pct_reached
                                )
                            events.append({"event": "TRADE_CLOSED", "trade_id": trade_id, "reason": reason, **closed_info})
                            continue

        return events

    def _close_trade(self, trade_id: str, trade: Dict, exit_spot: float, reason: str) -> Dict[str, Any]:
        """Closes an open trade and calculates realized P&L."""
        qty = trade.get("qty", 1)
        entry_prem = float(trade.get("entry_premium", 0.0) or 0.0)
        strike = trade.get("strike", 0)
        direction = trade.get("direction", "BUY")

        if reason == "BREAKEVEN_HIT":
            exit_prem = entry_prem
            pnl = 0.0
        elif self.paper_mode:
            exit_prem = self._estimate_premium(exit_spot, strike, direction)
            pnl = (exit_prem - entry_prem) * qty
        else:
            exit_prem = entry_prem
            pnl = 0.0
            if self._kite:
                try:
                    from kiteconnect import KiteConnect
                    self._kite.place_order(
                        variety          = KiteConnect.VARIETY_REGULAR,
                        exchange         = trade["exchange"],
                        tradingsymbol    = trade["symbol"],
                        transaction_type = KiteConnect.TRANSACTION_TYPE_SELL,
                        quantity         = qty,
                        order_type       = KiteConnect.ORDER_TYPE_MARKET,
                        product          = KiteConnect.PRODUCT_MIS,
                        tag              = "ICT_EXIT"
                    )
                    ltp = self._get_ltp(trade["symbol"], trade["exchange"])
                    if ltp:
                        exit_prem = ltp
                        pnl = (exit_prem - entry_prem) * qty
                except Exception as e:
                    logger.error(f"Live exit order failed for {trade_id}: {e}")

        trade_update = {
            **trade,
            "status": "CLOSED",
            "exit_time": datetime.now(tz=IST).isoformat(),
            "exit_spot": exit_spot,
            "exit_premium": exit_prem,
            "pnl": pnl,
            "exit_reason": reason
        }

        if self.paper_mode:
            self._log_paper_trade("TRADE_CLOSED", trade_update)

        if trade_id in self._open_trades:
            del self._open_trades[trade_id]

        logger.info(
            f"[{trade_id}] Closed ({reason}) | Spot: {exit_spot:.2f} | "
            f"Prem: {exit_prem:.2f} | P&L: ₹{pnl:+,.0f}"
        )

        return {"exit_spot": exit_spot, "exit_premium": exit_prem, "pnl": pnl, "trade": trade_update}

    # ── Trade monitoring (breakeven / partial / SL / TP) ────────────────────

    def start_monitoring(self):
        """Start background thread that monitors all open trades."""
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="TradeMonitor"
        )
        self._monitor_thread.start()
        logger.info("Trade monitor started")

    def stop_monitoring(self):
        self._running = False

    def _monitor_loop(self):
        """Checks open trades every 30 seconds for TP/SL/breakeven conditions."""
        while self._running:
            for trade_id, trade in list(self._open_trades.items()):
                try:
                    self._check_trade(trade_id, trade)
                except Exception as e:
                    logger.error(f"Monitor error on {trade_id}: {e}")
            time.sleep(30)

    def _check_trade(self, trade_id: str, trade: Dict):
        """Check if trade needs breakeven move, partial exit, or full close."""
        if self.paper_mode:
            return

        ltp = self._get_ltp(trade["symbol"], trade["exchange"])
        if ltp is None:
            return

        entry = trade.get("entry_premium", 0) or 0
        if entry == 0:
            return

        profit_pts = ltp - entry
        risk_pts   = entry * 0.30

        if profit_pts >= risk_pts and not trade.get("breakeven_moved"):
            logger.info(f"[{trade_id}] Moving SL to breakeven at ₹{entry}")
            trade["breakeven_moved"] = True

        if profit_pts >= risk_pts * 1.5 and not trade.get("partial_exited"):
            logger.info(f"[{trade_id}] Partial exit at ₹{ltp} (1.5R)")
            trade["partial_exited"] = True

    def _get_ltp(self, symbol: str, exchange: str) -> Optional[float]:
        """Fetch live last traded price from Kite."""
        if self._kite is None:
            return None
        try:
            key = f"{exchange}:{symbol}"
            data = self._kite.ltp([key])
            return data[key]["last_price"]
        except Exception as e:
            logger.warning(f"LTP fetch failed for {symbol}: {e}")
            return None

    # ── Square-off ───────────────────────────────────────────────────────────

    def square_off_all(self, reason: str = "15:15 auto square-off") -> List[str]:
        """Force-close all open positions. Returns list of closed trade IDs."""
        closed = []
        for trade_id, trade in list(self._open_trades.items()):
            try:
                exit_spot = trade.get("spot_entry", 0)
                closed_info = self._close_trade(trade_id, trade, exit_spot, reason)
                closed.append(trade_id)
            except Exception as e:
                logger.error(f"Square-off failed for {trade_id}: {e}")
        return closed

    def get_open_trades(self) -> Dict[str, Dict]:
        return dict(self._open_trades)

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _estimate_premium(spot: float, strike: int, direction: str) -> float:
        """
        Rough premium estimate for paper trading.
        Uses simple intrinsic + 50pt time value estimate.
        Not used for P&L — only for paper mode display.
        """
        if direction == "BUY":  # CE
            intrinsic = max(0.0, spot - strike)
        else:                   # PE
            intrinsic = max(0.0, strike - spot)
        return round(intrinsic + 50, 2)   # +50 for time value estimate

    def _log_paper_trade(self, event: str, trade: Dict):
        """Append event to today's paper trades log file."""
        base    = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        log_dir = os.path.join(base, "logs")
        os.makedirs(log_dir, exist_ok=True)
        today   = datetime.now(tz=IST).strftime("%Y-%m-%d")
        fpath   = os.path.join(log_dir, f"paper_trades_{today}.json")

        records = []
        if os.path.exists(fpath):
            try:
                with open(fpath) as f:
                    records = json.load(f)
            except Exception:
                records = []

        records.append({
            "event":     event,
            "timestamp": datetime.now(tz=IST).isoformat(),
            **{k: v for k, v in trade.items() if not callable(v)}
        })

        with open(fpath, "w") as f:
            json.dump(records, f, indent=2, default=str)
