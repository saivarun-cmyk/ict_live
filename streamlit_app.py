"""
Streamlit Cloud Entrypoint for ICT Predictive Signals Engine.
Supports deployment to Streamlit Community Cloud (share.streamlit.io).
"""

import os
import json
import yaml
from datetime import datetime
import zoneinfo
import streamlit as st
import streamlit.components.v1 as components

from src.indicator.engine import ICTPredictiveEngine
from src.data.upstox_client import UpstoxClient

IST = zoneinfo.ZoneInfo("Asia/Kolkata")

# Configure Streamlit page
st.set_page_config(
    page_title="ICT Predictive Signals Engine",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Load secrets from st.secrets if available (Streamlit Cloud), fallback to os.environ / .env
def get_secret(key: str, default: str = "") -> str:
    if hasattr(st, "secrets") and key in st.secrets:
        return str(st.secrets[key])
    return os.getenv(key, default)

# Set environment variables for engine / client
for k in ["UPSTOX_ACCESS_TOKEN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "MOCK_REPLAY"]:
    val = get_secret(k)
    if val:
        os.environ[k] = val

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

@st.cache_data
def load_config():
    with open(os.path.join(BASE_DIR, "config", "settings.yaml")) as f:
        settings = yaml.safe_load(f)
    with open(os.path.join(BASE_DIR, "config", "instruments.yaml")) as f:
        instruments = yaml.safe_load(f)
    return settings, instruments

settings_cfg, instruments_cfg = load_config()

# Sidebar: Controls
st.sidebar.title("ICT Engine Controls")

# Market Hours status
now_ist = datetime.now(tz=IST)
weekday = now_ist.weekday()
minutes = now_ist.hour * 60 + now_ist.minute
is_open = (weekday < 5) and (9 * 60 + 15 <= minutes < 15 * 60 + 30)

if is_open:
    st.sidebar.success(f"🟢 MARKET OPEN ({now_ist.strftime('%H:%M:%S')} IST)")
else:
    st.sidebar.error(f"🔴 MARKET CLOSED ({now_ist.strftime('%H:%M:%S')} IST)")

# Asset selection
indices = [idx["name"] for idx in instruments_cfg.get("indices", [])]
selected_name = st.sidebar.selectbox("Select Asset", indices, index=0)

asset_map = {idx["name"]: idx["instrument_key"] for idx in instruments_cfg.get("indices", [])}
instrument_key = asset_map.get(selected_name, "NSE_INDEX|Nifty 50")

# Timeframe selection
timeframe = st.sidebar.radio("Timeframe", ["1m", "5m", "15m"], index=1, horizontal=True)

# Toggles
st.sidebar.markdown("### Indicators")
show_fvg = st.sidebar.checkbox("FVG Zones", value=True)
show_ob = st.sidebar.checkbox("Order Blocks & Breakers", value=True)
show_liq = st.sidebar.checkbox("PDH / PDL & Liquidity", value=True)
show_signals = st.sidebar.checkbox("Signals & Trades", value=True)

# Engine initialization
engine = ICTPredictiveEngine(settings_cfg)
data_client = UpstoxClient()

tf_map = {"1m": "1minute", "5m": "5minute", "15m": "15minute"}
interval = tf_map.get(timeframe, "5minute")

with st.spinner(f"Evaluating ICT order flow for {selected_name}..."):
    candles = data_client.fetch_historical_candles(instrument_key, interval=interval, days=5)
    htf_candles = data_client.fetch_historical_candles(instrument_key, interval="30minute", days=10)
    result = engine.evaluate(candles, htf_candles=htf_candles)

if not candles:
    st.error("No candle data available.")
    st.stop()

last_candle = candles[-1]
prev_candle = candles[-2] if len(candles) > 1 else last_candle
diff = last_candle.close - prev_candle.close
pct = (diff / prev_candle.close) * 100

db = result.get("dashboard", {})

# Top metric summary cards
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Last Price", f"{last_candle.close:.2f}", f"{diff:+.2f} ({pct:+.2f}%)")
c2.metric("Signal", db.get("signal", "HOLD"))
c3.metric("IPDA Phase", db.get("ipda_phase", "--"))
c4.metric("Last Model", db.get("last_model", "--"))
c5.metric("CISD State", db.get("cisd_state", "--"))
c6.metric("HTF Bias", db.get("htf_bias", "--"))

# Prepare formatted data for lightweight chart embed
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

candles_json = json.dumps(formatted_candles)
indicators_json = json.dumps(result)
options_json = json.dumps({
    "showFVG": show_fvg,
    "showOB": show_ob,
    "showLiq": show_liq,
    "showSignals": show_signals
})

# Read chart.js code
with open(os.path.join(BASE_DIR, "web", "js", "chart.js"), "r") as f:
    chart_js_code = f.read()

# Build self-contained HTML embed with TradingView Lightweight Charts & ICT Series Primitive
html_content = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <script src="https://unpkg.com/lightweight-charts@4.2.1/dist/lightweight-charts.standalone.production.js"></script>
  <style>
    body {{ margin: 0; padding: 0; background: #131722; font-family: -apple-system, BlinkMacSystemFont, sans-serif; overflow: hidden; }}
    #chartStage {{ width: 100vw; height: 680px; position: relative; }}
  </style>
</head>
<body>
  <div id="chartStage"></div>
  <script>
    {chart_js_code}

    const chart = new ICTChart('chartStage');
    const candles = {candles_json};
    const indicators = {indicators_json};
    const options = {options_json};

    chart.setChartData({{
      candles: candles,
      indicators: indicators,
      isInitial: true,
      options: options
    }});
  </script>
</body>
</html>
"""

components.html(html_content, height=700)

# Display recent alerts table
st.subheader("Recent Order Flow Signals & Trades")
signals = result.get("signals", [])
if signals:
    sig_data = [
        {
            "Time (IST)": datetime.fromtimestamp(s["time"], tz=IST).strftime("%Y-%m-%d %H:%M"),
            "Signal": s["signal"],
            "Entry Model": s["model"],
            "Entry Price": f"{s['entry_price']:.2f}",
            "Stop Loss": f"{s['sl_price']:.2f}",
            "Take Profit (2:1)": f"{s['tp_price']:.2f}",
        }
        for s in reversed(signals[-10:])
    ]
    st.dataframe(sig_data, use_container_width=True)
else:
    st.info("No active predictive signals fired in the current lookback window. Order flow monitoring active.")
