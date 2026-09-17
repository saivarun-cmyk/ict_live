"""
FastAPI Server for ICT Predictive Signals Engine.
Provides REST APIs for chart data, configuration, and WebSockets for real-time streaming.
"""

import os
import json
import yaml
import asyncio
import logging
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from ..indicator.models import Candle
from ..indicator.engine import ICTPredictiveEngine
from ..data.upstox_client import UpstoxClient
from ..alerts.telegram import TelegramNotifier

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
load_dotenv(os.path.join(BASE_DIR, ".env"))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("AppServer")

app = FastAPI(title="ICT Predictive Signals Engine", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
WEB_DIR = os.path.join(BASE_DIR, "web")

def load_yaml(filename: str) -> Dict[str, Any]:
    with open(os.path.join(CONFIG_DIR, filename), "r") as f:
        return yaml.safe_load(f) or {}

def save_yaml(filename: str, data: Dict[str, Any]):
    with open(os.path.join(CONFIG_DIR, filename), "w") as f:
        yaml.dump(data, f, default_flow_style=False)

settings_cfg = load_yaml("settings.yaml")
instruments_cfg = load_yaml("instruments.yaml")

engine = ICTPredictiveEngine(settings_cfg)
data_client = UpstoxClient()
notifier = TelegramNotifier()
# Set of already notified signal signatures: {symbol_time_signal_price}
notified_signals = set()

def dispatch_alerts_for_result(instrument_name: str, result: Dict[str, Any], latest_timestamp: int):
    if not notifier.is_enabled() or not result:
        return
    # 1. Regular ICT Signals
    for s in result.get("signals", []):
        sig_time = s.get("time", 0)
        # Only notify signals that are current or recent
        if abs(latest_timestamp - sig_time) <= 1800:
            sig_id = f"{instrument_name}_{sig_time}_{s.get('signal')}_{s.get('entry_price')}"
            if sig_id not in notified_signals:
                notified_signals.add(sig_id)
                notifier.notify_signal(instrument_name, s)
                logger.info(f"Dispatched Telegram alert for {instrument_name} {s.get('signal')}")

    # 2. Silver Bullet Events
    for ev in result.get("silver_bullet_events", []):
        ev_time = ev.get("time", 0)
        if abs(latest_timestamp - ev_time) <= 1800:
            ev_id = f"{instrument_name}_{ev_time}_{ev.get('type')}_{ev.get('price')}"
            if ev_id not in notified_signals:
                notified_signals.add(ev_id)
                notifier.notify_silver_bullet(instrument_name, ev)
                logger.info(f"Dispatched Telegram Silver Bullet alert for {instrument_name} {ev.get('type')}")

@app.get("/api/test-telegram")
async def test_telegram():
    if not notifier.is_enabled():
        return {"status": "error", "message": "Telegram is not configured in .env"}
    ok = notifier.send_message("🔔 <b>ICT Predictive Signals Engine</b>: Test Telegram alert received successfully!")
    return {"status": "success" if ok else "failed", "sent": ok}


# Active WebSocket connections
active_connections: List[WebSocket] = []

@app.get("/api/instruments")
async def get_instruments():
    """Returns active indices and configurable stocks."""
    inst = load_yaml("instruments.yaml")
    indices = [x for x in inst.get("indices", []) if x.get("enabled", True)]
    stocks = [x for x in inst.get("stocks", []) if x.get("enabled", True)]
    all_stocks = inst.get("stocks", [])
    return {
        "indices": indices,
        "active_stocks": stocks,
        "all_stocks": all_stocks
    }

@app.get("/api/settings")
async def get_settings():
    return load_yaml("settings.yaml")

@app.post("/api/settings")
async def update_settings(new_settings: Dict[str, Any]):
    global engine, settings_cfg
    settings_cfg.update(new_settings)
    save_yaml("settings.yaml", settings_cfg)
    engine = ICTPredictiveEngine(settings_cfg)
    return {"status": "success", "settings": settings_cfg}

@app.get("/api/chart-data")
async def get_chart_data(
    instrument_key: str = Query("NSE_INDEX|Nifty 50"),
    timeframe: str = Query("5m")
):
    """
    Fetches candles, executes the complete ICT Pine Script indicator logic,
    and returns chart candlesticks + overlays + dashboard state.
    """
    tf_map = {
        "1m": "1minute",
        "5m": "5minute",
        "15m": "15minute"
    }
    interval = tf_map.get(timeframe, "5minute")
    
    # 1. Fetch candles for active timeframe
    candles = data_client.fetch_historical_candles(instrument_key, interval=interval, days=5)
    
    # 2. Fetch HTF candles (30m) for HTF trend bias
    htf_candles = data_client.fetch_historical_candles(instrument_key, interval="30minute", days=10)

    # 3. Evaluate ICT engine
    result = engine.evaluate(candles, htf_candles=htf_candles)
    
    # Format candles for TradingView Lightweight Charts
    formatted_candles = [
        {
            "time": c.timestamp,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume
        }
        for c in candles
    ]

    # Dispatch Telegram notifications if fresh predictive signals detected
    inst_name = instrument_key.split("|")[-1] if "|" in instrument_key else instrument_key
    latest_ts = formatted_candles[-1]["time"] if formatted_candles else 0
    dispatch_alerts_for_result(inst_name, result, latest_ts)

    return {
        "instrument_key": instrument_key,
        "timeframe": timeframe,
        "candles": formatted_candles,
        "indicators": result
    }

@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            # Keep-alive loop, receives requests or sends heartbeats
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in active_connections:
            active_connections.remove(websocket)

# Mount frontend web assets
if os.path.exists(WEB_DIR):
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
