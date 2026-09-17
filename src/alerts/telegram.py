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
        """Formats and dispatches BUY/SELL alerts matching Pine Script format."""
        sig = signal_data.get("signal", "HOLD")
        icon = "🟢" if sig == "BUY" else "🔴"
        model = signal_data.get("model", "2022 Model")
        tier = signal_data.get("tier", "Swing")
        entry = signal_data.get("entry_price", 0.0)
        sl = signal_data.get("sl_price", 0.0)
        tp = signal_data.get("tp_price", 0.0)
        exit_plan = signal_data.get("exit_plan", "")
        cisd = signal_data.get("cisd", "NEUTRAL")

        msg = (
            f"<b>{icon} {symbol} | ICT Predictive {sig}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Model:</b> {model} [{tier}]\n"
            f"<b>CISD State:</b> {cisd}\n"
            f"<b>Entry:</b> <code>{entry:.2f}</code>\n"
            f"<b>Stop Loss:</b> <code>{sl:.2f}</code>\n"
            f"<b>Take Profit:</b> <code>{tp:.2f}</code> (2:1 R:R)\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Exit Plan:</b> {exit_plan}"
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
