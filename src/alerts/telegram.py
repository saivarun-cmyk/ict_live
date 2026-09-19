"""
Telegram Alert Dispatcher
Sends formatted HTML notifications for ICT Predictive Signals & Silver Bullet events.
"""

import os
import logging
import requests
from typing import Dict, Any, Optional

logger = logging.getLogger("TelegramAlerts")

class TelegramNotifier:
    def __init__(self, bot_token: str = "", chat_id: str = ""):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage" if self.bot_token else ""

    def is_enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send_message(self, text: str) -> bool:
        if not self.is_enabled():
            logger.debug("Telegram not configured. Skipping alert.")
            return False

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        try:
            resp = requests.post(self.api_url, json=payload, timeout=5)
            if resp.status_code == 200:
                logger.info("Telegram alert sent successfully.")
                return True
            else:
                logger.error(f"Telegram API failed: {resp.status_code} - {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    def notify_signal(self, symbol: str, signal_data: Dict[str, Any]):
        """Formats and dispatches BUY/SELL alerts matching Pine Script format with Institutional Agent Brain grading."""
        sig = signal_data.get("signal", "HOLD")
        icon = "🟢" if sig == "BUY" else "🔴"
        model = signal_data.get("model", "2022 Model")
        tier = signal_data.get("tier", "Swing")
        entry = signal_data.get("entry_price", 0.0)
        sl = signal_data.get("sl_price", 0.0)
        tp = signal_data.get("tp_price", 0.0)
        exit_plan = signal_data.get("exit_plan", "")
        cisd = signal_data.get("cisd", "NEUTRAL")

        grade = signal_data.get("grade", "A")
        score = signal_data.get("confluence_score", 0)
        factors = signal_data.get("confluence_factors", [])
        factors_str = "\n • " + "\n • ".join(factors) if factors else "Standard Confluence"
        grade_badge = "⭐️ A+" if grade == "A+" else ("🌟 A" if grade == "A" else f"⚡️ {grade}")

        msg = (
            f"<b>{icon} {symbol} | ICT Predictive {sig}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Grade:</b> {grade_badge} (Score: <b>{score}/100</b>)\n"
            f"<b>Model:</b> {model} [{tier}]\n"
            f"<b>CISD State:</b> {cisd}\n"
            f"<b>Entry:</b> <code>{entry:.2f}</code>\n"
            f"<b>Stop Loss:</b> <code>{sl:.2f}</code>\n"
            f"<b>Take Profit:</b> <code>{tp:.2f}</code> (2:1 R:R)\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Institutional Confluences:</b>{factors_str}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Exit Plan:</b> {exit_plan}"
        )
        self.send_message(msg)

    def notify_judas_swing(self, symbol: str, event_data: Dict[str, Any]):
        """Judas Swing Opening Range Trap specific notification."""
        ev_type = event_data.get("type", "")
        direction = "BUY (Long Reversal)" if "BUY" in ev_type else "SELL (Short Reversal)"
        icon = "🟢" if "BUY" in ev_type else "🔴"
        price = event_data.get("entry_price", 0.0)
        sl = event_data.get("sl", 0.0)
        tp = event_data.get("tp", 0.0)
        score = event_data.get("score", 0)
        grade = event_data.get("grade", "A")

        msg = (
            f"<b>🪤 {symbol} | JUDAS SWING DETECTED</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Direction:</b> {icon} {direction}\n"
            f"<b>Trap:</b> Opening Range Liquidity Trapped\n"
            f"<b>Grade:</b> ⭐️ {grade} (Score: <b>{score}/100</b>)\n"
            f"<b>Entry:</b> <code>{price:.2f}</code> | <b>SL:</b> <code>{sl:.2f}</code> | <b>TP:</b> <code>{tp:.2f}</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<i>Institutional rule: Retail breakout orders absorbed. Reversing to opposite liquidity!</i>"
        )
        self.send_message(msg)

    def notify_turtle_soup(self, symbol: str, event_data: Dict[str, Any]):
        """Turtle Soup False Breakout notification."""
        ev_type = event_data.get("type", "")
        direction = "BUY (Long Reversal)" if "BUY" in ev_type else "SELL (Short Reversal)"
        icon = "🟢" if "BUY" in ev_type else "🔴"
        price = event_data.get("entry_price", 0.0)
        level = event_data.get("level", 0.0)
        sl = event_data.get("sl", 0.0)
        tp = event_data.get("tp", 0.0)
        score = event_data.get("score", 0)
        grade = event_data.get("grade", "A")

        msg = (
            f"<b>🐢 {symbol} | TURTLE SOUP REVERSAL</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Direction:</b> {icon} {direction}\n"
            f"<b>Swept Level:</b> <code>{level:.2f}</code> (False Breakout Rejected)\n"
            f"<b>Grade:</b> ⭐️ {grade} (Score: <b>{score}/100</b>)\n"
            f"<b>Entry:</b> <code>{price:.2f}</code> | <b>SL:</b> <code>{sl:.2f}</code> | <b>TP:</b> <code>{tp:.2f}</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<i>Institutional rule: Smart money raided HTF liquidity, rejecting back inside.</i>"
        )
        self.send_message(msg)

    def notify_silver_bullet(self, symbol: str, event_data: Dict[str, Any]):
        """Silver bullet specific triggers and exits."""
        ev_type = event_data.get("type", "")
        price = event_data.get("price", 0.0)

        if "BUY" in ev_type:
            msg = (
                f"<b>🥈 {symbol} | SILVER BULLET BUY</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"<b>Structure:</b> Sweep ➔ MSS ➔ Fresh FVG ➔ Entry\n"
                f"<b>Price:</b> <code>{price:.2f}</code>\n"
                f"<b>SL:</b> <code>{event_data.get('sl', 0.0):.2f}</code> | "
                f"<b>TP:</b> <code>{event_data.get('tp', 0.0):.2f}</code>\n"
                f"<b>Exit:</b> Time-boxed - close by end of Killzone hour"
            )
        elif "SELL" in ev_type:
            msg = (
                f"<b>🥈 {symbol} | SILVER BULLET SELL</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"<b>Structure:</b> Sweep ➔ MSS ➔ Fresh FVG ➔ Entry\n"
                f"<b>Price:</b> <code>{price:.2f}</code>\n"
                f"<b>SL:</b> <code>{event_data.get('sl', 0.0):.2f}</code> | "
                f"<b>TP:</b> <code>{event_data.get('tp', 0.0):.2f}</code>\n"
                f"<b>Exit:</b> Time-boxed - close by end of Killzone hour"
            )
        elif ev_type == "TP_HIT":
            msg = f"<b>🥈 {symbol} | SILVER BULLET CLOSED: TP HIT (WIN) 🎯</b> at <code>{price:.2f}</code>"
        elif ev_type == "SL_HIT":
            msg = f"<b>🥈 {symbol} | SILVER BULLET CLOSED: SL HIT (LOSS) 🛑</b> at <code>{price:.2f}</code>"
        elif ev_type == "TIME_BOXED_EXIT":
            msg = f"<b>🥈 {symbol} | SILVER BULLET CLOSED: Killzone Ended ⏱️</b> at <code>{price:.2f}</code>"
        else:
            msg = f"<b>🥈 {symbol} | SILVER BULLET Event:</b> {ev_type} at {price:.2f}"

        self.send_message(msg)

    def _send(self, text: str) -> bool:
        """Compatibility alias for send_message."""
        return self.send_message(text)

    def notify_breakeven(self, symbol: str, trade: Dict[str, Any], current_price: float):
        """Notifies when a trade achieves +1R expansion and SL is moved to Breakeven."""
        direction = trade.get("direction", "BUY")
        entry = trade.get("spot_entry", 0.0)
        model = trade.get("model", "ICT Setup")
        risk_pts = trade.get("risk_pts", 0.0)

        msg = (
            f"<b>🛡️ {symbol} | RISK-FREE DEFENSE ACTIVATED</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Setup:</b> {model} ({direction})\n"
            f"<b>Expansion:</b> +1.0R reached at <code>{current_price:.2f}</code>\n"
            f"<b>Desk Action:</b> Stop Loss moved to Breakeven (<code>{entry:.2f}</code>)\n"
            f"<b>Open Risk:</b> <b>₹0.00 (Risk-Free Trade)</b> 🔒\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<i>Institutional rule: Capital protected. Runners targeting TP.</i>"
        )
        self.send_message(msg)

    def notify_trailing_sl_moved(
        self,
        symbol: str,
        trade: Dict[str, Any],
        new_sl: float,
        locked_r: float,
        peak_price: float,
        locked_pnl: float
    ):
        """Notifies when the trailing ratchet steps forward, locking in higher profit."""
        direction = trade.get("direction", "BUY")
        entry = trade.get("spot_entry", 0.0)
        model = trade.get("model", "ICT Setup")

        msg = (
            f"<b>🔒 {symbol} | TRAILING STOP ADVANCED</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Setup:</b> {model} ({direction})\n"
            f"<b>Peak Price Reached:</b> <code>{peak_price:.2f}</code>\n"
            f"<b>New Trailed SL:</b> <code>{new_sl:.2f}</code> (+{locked_r:.1f}R locked)\n"
            f"<b>Guaranteed Profit:</b> <b>+₹{locked_pnl:,.0f}</b> 💰\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<i>Human ICT Desk: Ratchet mechanism advanced. Profits permanently banked.</i>"
        )
        self.send_message(msg)

    def notify_near_tp_lock(
        self,
        symbol: str,
        trade: Dict[str, Any],
        exit_price: float,
        pnl_pts: float,
        pnl_inr: float,
        pct_reached: float
    ):
        """Notifies when a trade approaches TP (e.g. 85-90%) and locks in profit on stall."""
        direction = trade.get("direction", "BUY")
        model = trade.get("model", "ICT Setup")
        entry = trade.get("spot_entry", 0.0)
        tp = trade.get("spot_tp", 0.0)

        msg = (
            f"<b>🎯 {symbol} | PROXIMITY PROFIT HARVEST</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Setup:</b> {model} ({direction})\n"
            f"<b>Target Proximity:</b> {pct_reached:.1f}% of TP reached\n"
            f"<b>Target TP:</b> <code>{tp:.2f}</code> | <b>Exited @</b> <code>{exit_price:.2f}</code>\n"
            f"<b>Desk Action:</b> Liquidity absorption/stall detected. Profit booked.\n"
            f"<b>Secured Gain:</b> +{pnl_pts:.1f} pts (+₹{pnl_inr:,.0f}) 💰\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<i>Human ICT Desk: Protect the bag, never let 85%+ winners retrace.</i>"
        )
        self.send_message(msg)

    def notify_trade_closed(
        self,
        symbol: str,
        trade: Dict[str, Any],
        reason: str,
        exit_price: float,
        pnl_inr: float
    ):
        """Notifies full trade resolution (TP, SL, Breakeven, or Time-boxed)."""
        direction = trade.get("direction", "BUY")
        model = trade.get("model", "ICT Setup")
        entry = trade.get("spot_entry", 0.0)

        if reason == "BREAKEVEN_HIT":
            icon = "⚪"
            verdict = "BREAKEVEN SCRATCH (₹0 LOSS) 🛡️"
        elif reason == "TRAILING_SL_HIT":
            icon = "🔒"
            verdict = f"TRAILING STOP PROFIT SECURED 💰 (+₹{pnl_inr:,.0f})"
        elif reason == "TP_HIT":
            icon = "🟢"
            verdict = f"FULL TAKE PROFIT HIT 🎯 (+₹{pnl_inr:,.0f})"
        elif reason == "SL_HIT":
            icon = "🔴"
            verdict = f"STOP LOSS HIT 🛑 (-₹{abs(pnl_inr):,.0f})"
        else:
            icon = "⏱️"
            verdict = f"{reason} | P&L: ₹{pnl_inr:+,.0f}"

        msg = (
            f"<b>{icon} {symbol} | TRADE CLOSED: {verdict}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Setup:</b> {model} ({direction})\n"
            f"<b>Entry:</b> <code>{entry:.2f}</code> ➔ <b>Exit:</b> <code>{exit_price:.2f}</code>\n"
            f"<b>Reason:</b> {reason}\n"
            f"<b>Realized P&L:</b> <b>₹{pnl_inr:+,.0f}</b>"
        )
        self.send_message(msg)

    def notify_pyramid(
        self,
        symbol: str,
        primary_trade: Dict[str, Any],
        new_signal: Dict[str, Any]
    ):
        """Notifies when a secondary setup is added because the primary setup is risk-free."""
        direction = new_signal.get("signal", "BUY")
        new_model = new_signal.get("model", "Silver Bullet")
        entry = new_signal.get("entry_price", 0.0)

        msg = (
            f"<b>⚡ {symbol} | INSTITUTIONAL PYRAMID EXECUTION</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Primary Setup:</b> {primary_trade.get('model')} (Protected at Breakeven)\n"
            f"<b>Secondary Setup:</b> {new_model} ({direction}) @ <code>{entry:.2f}</code>\n"
            f"<b>Desk Status:</b> Primary risk is ₹0. Stacking confluence position!\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<i>Pro Desk: Adding size to high-conviction winning order flow.</i>"
        )
        self.send_message(msg)

