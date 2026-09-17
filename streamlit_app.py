"""
Streamlit Cloud Entrypoint for ICT Predictive Signals Engine.
Delivers the exact same high-definition TradingView native UI inside Streamlit Cloud,
with real-time Upstox data, ICT order flow calculations, and automated Telegram alerts.
"""

import os
import json
import yaml
import time
from datetime import datetime
import zoneinfo
import streamlit as st
import streamlit.components.v1 as components

from src.indicator.engine import ICTPredictiveEngine
from src.data.upstox_client import UpstoxClient
from src.alerts.telegram import TelegramNotifier

IST = zoneinfo.ZoneInfo("Asia/Kolkata")

st.set_page_config(
    page_title="ICT Predictive Signals Engine",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Streamlit CSS: Remove default margins and headers to give 100% full-screen TradingView space
st.markdown("""
<style>
  #MainMenu {visibility: hidden !important; display: none !important;}
  header {visibility: hidden !important; display: none !important;}
  footer {visibility: hidden !important; display: none !important;}
  div[data-testid="stToolbar"] {visibility: hidden !important; display: none !important;}
  div[data-testid="stDecoration"] {visibility: hidden !important; display: none !important;}
  div[data-testid="stStatusWidget"] {visibility: hidden !important; display: none !important;}
  .block-container {
    padding: 0 !important;
    margin: 0 !important;
    max-width: 100% !important;
    width: 100% !important;
  }
  iframe {
    width: 100vw !important;
    height: 820px !important;
    border: none !important;
    display: block !important;
    overflow: hidden !important;
  }
</style>
""", unsafe_allow_html=True)

# Helper to read secrets from st.secrets (Streamlit Cloud) or .env / os.environ
def get_secret(key: str, default: str = "") -> str:
    try:
        if hasattr(st, "secrets") and key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.getenv(key, default)

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

engine = ICTPredictiveEngine(settings_cfg)
data_client = UpstoxClient()
notifier = TelegramNotifier()

# Maintain alerted signals in session state so we don't spam duplicate alerts
if "notified_signals" not in st.session_state:
    st.session_state["notified_signals"] = set()

def dispatch_alerts_for_result(instrument_name: str, tf_label: str, result: dict, latest_timestamp: int):
    if not notifier.is_enabled() or not result:
        return
    for s in result.get("signals", []):
        sig_time = s.get("time", 0)
        if abs(latest_timestamp - sig_time) <= 1800:
            sig_id = f"{instrument_name}_{tf_label}_{sig_time}_{s.get('signal')}_{s.get('entry_price')}"
            if sig_id not in st.session_state["notified_signals"]:
                st.session_state["notified_signals"].add(sig_id)
                notifier.notify_signal(f"{instrument_name} ({tf_label})", s)

    for ev in result.get("silver_bullet_events", []):
        ev_time = ev.get("time", 0)
        if abs(latest_timestamp - ev_time) <= 1800:
            ev_id = f"{instrument_name}_{tf_label}_{ev_time}_{ev.get('type')}_{ev.get('price')}"
            if ev_id not in st.session_state["notified_signals"]:
                st.session_state["notified_signals"].add(ev_id)
                notifier.notify_silver_bullet(f"{instrument_name} ({tf_label})", ev)

# Preload data for all 3 indices across 1m, 5m, and 15m timeframes
indices = instruments_cfg.get("indices", [])
timeframe_configs = [
    ("1m", "1minute", 2),
    ("5m", "5minute", 4),
    ("15m", "15minute", 8)
]

preloaded_data = {}

for item in indices:
    key = item["instrument_key"]
    name = item["name"]
    symbol = item["symbol"]
    htf = data_client.fetch_historical_candles(key, interval="30minute", days=10)

    for tf_label, interval, days in timeframe_configs:
        candles = data_client.fetch_historical_candles(key, interval=interval, days=days)
        res = engine.evaluate(candles, htf_candles=htf)
        
        latest_ts = candles[-1].timestamp if candles else 0
        dispatch_alerts_for_result(name, tf_label, res, latest_ts)

        combo_key = f"{key}_{tf_label}"
        data_entry = {
            "name": name,
            "symbol": symbol,
            "timeframe": tf_label,
            "candles": [
                {
                    "time": c.timestamp,
                    "open": c.open,
                    "high": c.high,
                    "low": c.low,
                    "close": c.close,
                    "volume": c.volume
                }
                for c in candles
            ],
            "indicators": res
        }
        preloaded_data[combo_key] = data_entry
        if tf_label == "5m":
            preloaded_data[key] = data_entry

# Read CSS and chart.js
with open(os.path.join(BASE_DIR, "web", "css", "style.css")) as f:
    css_content = f.read()

with open(os.path.join(BASE_DIR, "web", "js", "chart.js")) as f:
    chart_js_content = f.read()

data_json = json.dumps(preloaded_data)

# Full self-contained TradingView application matching web/index.html 100%
full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ICT Predictive Signals Engine</title>
  <!-- Lightweight Charts v4.2.1 -->
  <script src="https://unpkg.com/lightweight-charts@4.2.1/dist/lightweight-charts.standalone.production.js"></script>
  <!-- Lucide Icons -->
  <script src="https://unpkg.com/lucide@latest"></script>
  <style>
    {css_content}
    html, body {{
      width: 100%;
      height: 100%;
      overflow: hidden !important;
      margin: 0;
      padding: 0;
    }}
    .tv-app-container {{
      width: 100%;
      height: 100%;
      display: flex;
      flex-direction: column;
      overflow: hidden !important;
    }}
    .tv-chart-viewport {{
      flex: 1 1 0% !important;
      min-height: 0 !important;
      overflow: hidden !important;
      position: relative !important;
      display: flex !important;
      flex-direction: column !important;
    }}
    .tv-chart-stage {{
      flex: 1 1 0% !important;
      min-height: 0 !important;
      width: 100% !important;
      position: relative !important;
    }}
    .tv-bottom-bar {{
      height: 38px !important;
      min-height: 38px !important;
      max-height: 38px !important;
      flex-shrink: 0 !important;
    }}
  </style>
</head>
<body>
  <div class="tv-app-container">
    <!-- TOP TOOLBAR -->
    <header class="tv-top-toolbar">
      <div class="tv-toolbar-left">
        <div class="tv-brand">
          <div class="tv-logo-badge">TV</div>
          <span class="tv-title">ICT Predictive Signals</span>
        </div>

        <div class="tv-divider"></div>

        <!-- QUICK INSTRUMENT SWITCHER -->
        <div class="tv-instruments-bar" id="indicesButtons">
          <button class="tv-tool-btn active" data-symbol="NSE_INDEX|Nifty 50">NIFTY 50</button>
          <button class="tv-tool-btn" data-symbol="NSE_INDEX|Nifty Bank">BANK NIFTY</button>
          <button class="tv-tool-btn" data-symbol="BSE_INDEX|SENSEX">SENSEX</button>
        </div>

        <div class="tv-divider"></div>

        <!-- TIMEFRAME SELECTOR (1m, 5m, 15m) -->
        <div class="tv-timeframe-bar" id="tfButtons">
          <button class="tv-tf-btn" data-tf="1m">1m</button>
          <button class="tv-tf-btn active" data-tf="5m">5m</button>
          <button class="tv-tf-btn" data-tf="15m">15m</button>
        </div>
      </div>

      <!-- RIGHT CONTROLS: OVERLAYS & LIVE STATUS -->
      <div class="tv-toolbar-right">
        <!-- INDICATOR OVERLAY CHIPS -->
        <div class="tv-toggle-group">
          <label class="tv-chip active" id="toggleFVG">
            <input type="checkbox" checked>
            <span class="tv-chip-dot fvg"></span> FVG Zones
          </label>
          <label class="tv-chip active" id="toggleOB">
            <input type="checkbox" checked>
            <span class="tv-chip-dot ob"></span> Order Blocks
          </label>
          <label class="tv-chip active" id="toggleLiq">
            <input type="checkbox" checked>
            <span class="tv-chip-dot liq"></span> PDH / PDL
          </label>
          <label class="tv-chip active" id="toggleSignals">
            <input type="checkbox" checked>
            <span class="tv-chip-dot sig"></span> Signals & Trades
          </label>
        </div>

        <div class="tv-divider"></div>

        <!-- DYNAMIC MARKET STATUS BADGE -->
        <div id="marketStatusBadge" class="tv-market-badge closed" title="NSE / BSE Trading Session: 09:15 - 15:30 IST (Mon-Fri)">
          <span class="tv-market-dot"></span>
          <div class="tv-market-info">
            <span id="marketStatusText" class="tv-market-title">MARKET CLOSED</span>
            <span id="marketStatusSub" class="tv-market-sub">Opens 09:15 AM IST</span>
          </div>
        </div>

        <button id="refreshBtn" class="tv-icon-btn" title="Refresh Feed">
          <i data-lucide="rotate-cw"></i>
        </button>

        <div class="tv-divider"></div>

        <button id="zoomInBtn" class="tv-icon-btn" title="Zoom In (+)">
          <i data-lucide="zoom-in"></i>
        </button>
        <button id="zoomOutBtn" class="tv-icon-btn" title="Zoom Out (-)">
          <i data-lucide="zoom-out"></i>
        </button>
        <button id="resetZoomBtn" class="tv-icon-btn" title="Reset View (Auto)">
          <i data-lucide="maximize-2"></i>
        </button>
      </div>
    </header>

    <!-- CHART VIEWPORT -->
    <div class="tv-chart-viewport">
      <!-- TOP-LEFT TICKER HUD -->
      <div class="tv-ticker-hud">
        <div class="tv-ticker-main">
          <span class="tv-symbol-name" id="activeTickerTitle">NIFTY 50</span>
          <span class="tv-tf-tag" id="activeTimeframeBadge">5M</span>
          <span class="tv-last-price" id="activePrice">--</span>
          <span class="tv-chg-pill" id="priceChange">--</span>
        </div>
        <div class="tv-ticker-meta">
          <span>O: <b id="barO">--</b></span>
          <span>H: <b id="barH">--</b></span>
          <span>L: <b id="barL">--</b></span>
          <span>C: <b id="barC">--</b></span>
        </div>
      </div>

      <!-- PINE SCRIPT TOP-RIGHT FLOATING TABLE HUD (1:1 with TradingView Pine script) -->
      <div class="tv-pine-table-hud">
        <div class="tv-pine-table-header">
          <div class="tv-pine-title">
            <span class="tv-pine-logo">▲</span> ICT Predictive
          </div>
          <span id="dashSignalBadge" class="tv-pine-badge hold">HOLD</span>
        </div>
        <table class="tv-pine-table">
          <tbody>
            <tr>
              <td class="tv-td-lbl">Signal</td>
              <td class="tv-td-val" id="dashSignal">--</td>
            </tr>
            <tr>
              <td class="tv-td-lbl">Active Trade</td>
              <td class="tv-td-val" id="dashTradeEntry" style="font-weight:700;">Waiting</td>
            </tr>
            <tr>
              <td class="tv-td-lbl">SL / TP Targets</td>
              <td class="tv-td-val font-mono" id="dashTradeTargets">-- / --</td>
            </tr>
            <tr>
              <td class="tv-td-lbl">Active Setups</td>
              <td class="tv-td-val" id="dashSetupsCount" style="color:var(--tv-gold); font-weight:600;">--</td>
            </tr>
            <tr>
              <td class="tv-td-lbl">IPDA Phase</td>
              <td class="tv-td-val" id="dashIPDA">--</td>
            </tr>
            <tr>
              <td class="tv-td-lbl">Last Entry Model</td>
              <td class="tv-td-val" id="dashModel">--</td>
            </tr>
            <tr>
              <td class="tv-td-lbl">CISD State</td>
              <td class="tv-td-val" id="dashCISD">--</td>
            </tr>
            <tr>
              <td class="tv-td-lbl">Bull Sweep Active</td>
              <td class="tv-td-val" id="dashBullSweep">--</td>
            </tr>
            <tr>
              <td class="tv-td-lbl">Bear Sweep Active</td>
              <td class="tv-td-val" id="dashBearSweep">--</td>
            </tr>
            <tr>
              <td class="tv-td-lbl">PDH / PDL</td>
              <td class="tv-td-val font-mono" id="dashPDHPDL">-- / --</td>
            </tr>
            <tr>
              <td class="tv-td-lbl">In Killzone</td>
              <td class="tv-td-val" id="dashKZ">--</td>
            </tr>
            <tr>
              <td class="tv-td-lbl">Silver Bullet</td>
              <td class="tv-td-val" id="dashSB">--</td>
            </tr>
            <tr>
              <td class="tv-td-lbl">HTF Bias (30m)</td>
              <td class="tv-td-val" id="dashHTFBias">--</td>
            </tr>
            <tr>
              <td class="tv-td-lbl">Market Status</td>
              <td class="tv-td-val" id="dashMarketStatus">CLOSED</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- MAIN TRADINGVIEW LIGHTWEIGHT CHART -->
      <div id="tradingviewChart" class="tv-chart-stage"></div>

      <!-- TRADINGVIEW FLOATING ZOOM & AUTO BAR -->
      <div class="tv-floating-zoom-bar">
        <button id="floatZoomIn" class="tv-zoom-pill-btn" title="Zoom In (+)">+</button>
        <button id="floatZoomOut" class="tv-zoom-pill-btn" title="Zoom Out (−)">−</button>
        <button id="floatResetZoom" class="tv-zoom-pill-btn auto" title="Auto Scale / Reset View">Auto</button>
      </div>

      <!-- BOTTOM BAR FOR RECENT ALERTS -->
      <div class="tv-bottom-bar">
        <div class="tv-bottom-feed-title">
          <i data-lucide="bell" style="width:14px; height:14px;"></i> RECENT SIGNALS:
        </div>
        <div class="tv-alerts-ticker" id="signalsFeed">
          <span class="tv-alert-empty">Monitoring real-time order flow for liquidity sweeps and FVG touches...</span>
        </div>
      </div>
    </div>
  </div>

  <script>
    {chart_js_content}

    const ALL_DATA = {data_json};

    document.addEventListener('DOMContentLoaded', () => {{
      if (window.lucide) window.lucide.createIcons();

      const chart = new ICTChart('tradingviewChart');
      let currentInstrument = 'NSE_INDEX|Nifty 50';
      let currentInstrumentName = 'NIFTY 50';
      let currentTimeframe = '5m';

      function getActiveKey() {{
        return currentInstrument + '_' + currentTimeframe;
      }}

      // DOM Elements
      const activeTickerTitle = document.getElementById('activeTickerTitle');
      const activePrice = document.getElementById('activePrice');
      const priceChange = document.getElementById('priceChange');
      const activeTimeframeBadge = document.getElementById('activeTimeframeBadge');
      const refreshBtn = document.getElementById('refreshBtn');
      const indicesButtons = document.querySelectorAll('#indicesButtons .tv-tool-btn');
      const tfButtons = document.querySelectorAll('#tfButtons .tv-tf-btn');

      // Market Status Badge Elements
      const marketStatusBadge = document.getElementById('marketStatusBadge');
      const marketStatusText = document.getElementById('marketStatusText');
      const marketStatusSub = document.getElementById('marketStatusSub');
      const dashMarketStatus = document.getElementById('dashMarketStatus');

      // Zoom controls
      const zoomInBtn = document.getElementById('zoomInBtn');
      const zoomOutBtn = document.getElementById('zoomOutBtn');
      const resetZoomBtn = document.getElementById('resetZoomBtn');
      const floatZoomIn = document.getElementById('floatZoomIn');
      const floatZoomOut = document.getElementById('floatZoomOut');
      const floatResetZoom = document.getElementById('floatResetZoom');

      if (zoomInBtn) zoomInBtn.addEventListener('click', () => chart.zoomIn());
      if (zoomOutBtn) zoomOutBtn.addEventListener('click', () => chart.zoomOut());
      if (resetZoomBtn) resetZoomBtn.addEventListener('click', () => chart.resetZoom());
      if (floatZoomIn) floatZoomIn.addEventListener('click', () => chart.zoomIn());
      if (floatZoomOut) floatZoomOut.addEventListener('click', () => chart.zoomOut());
      if (floatResetZoom) floatResetZoom.addEventListener('click', () => chart.resetZoom());

      // OHLC elements
      const barO = document.getElementById('barO');
      const barH = document.getElementById('barH');
      const barL = document.getElementById('barL');
      const barC = document.getElementById('barC');

      // Toggles
      const toggleFVG = document.querySelector('#toggleFVG input');
      const toggleOB = document.querySelector('#toggleOB input');
      const toggleLiq = document.querySelector('#toggleLiq input');
      const toggleSignals = document.querySelector('#toggleSignals input');

      function getOverlayOptions() {{
        return {{
          showFVG: toggleFVG ? toggleFVG.checked : true,
          showOB: toggleOB ? toggleOB.checked : true,
          showLiq: toggleLiq ? toggleLiq.checked : true,
          showSignals: toggleSignals ? toggleSignals.checked : true
        }};
      }}

      // Pine Script Floating Table DOM
      const dashSignalBadge = document.getElementById('dashSignalBadge');
      const dashSignal = document.getElementById('dashSignal');
      const dashTradeEntry = document.getElementById('dashTradeEntry');
      const dashTradeTargets = document.getElementById('dashTradeTargets');
      const dashSetupsCount = document.getElementById('dashSetupsCount');
      const dashIPDA = document.getElementById('dashIPDA');
      const dashModel = document.getElementById('dashModel');
      const dashCISD = document.getElementById('dashCISD');
      const dashBullSweep = document.getElementById('dashBullSweep');
      const dashBearSweep = document.getElementById('dashBearSweep');
      const dashPDHPDL = document.getElementById('dashPDHPDL');
      const dashKZ = document.getElementById('dashKZ');
      const dashSB = document.getElementById('dashSB');
      const dashHTFBias = document.getElementById('dashHTFBias');
      const signalsFeed = document.getElementById('signalsFeed');

      let lastCandles = [];

      chart.chart.subscribeCrosshairMove(param => {{
        if (!param || !param.time || !param.seriesData || !param.seriesData.get(chart.candleSeries)) {{
          if (lastCandles.length > 0) updateOHLC(lastCandles[lastCandles.length - 1]);
          return;
        }}
        const d = param.seriesData.get(chart.candleSeries);
        updateOHLC(d);
      }});

      function updateOHLC(bar) {{
        if (!bar) return;
        barO.textContent = bar.open.toFixed(2);
        barH.textContent = bar.high.toFixed(2);
        barL.textContent = bar.low.toFixed(2);
        barC.textContent = bar.close.toFixed(2);
        barC.style.color = bar.close >= bar.open ? 'var(--tv-bull)' : 'var(--tv-bear)';
      }}

      // Real-time IST Market Hours
      function updateMarketStatusUI() {{
        const now = new Date();
        const parts = new Intl.DateTimeFormat('en-US', {{
          timeZone: 'Asia/Kolkata',
          hour12: false,
          weekday: 'short',
          hour: 'numeric',
          minute: 'numeric'
        }}).formatToParts(now);
        const map = {{}};
        for (const p of parts) map[p.type] = p.value;
        const weekday = map.weekday;
        const hour = parseInt(map.hour, 10);
        const min = parseInt(map.minute, 10);
        const total = hour * 60 + min;

        const isWeekday = !['Sat', 'Sun'].includes(weekday);
        const isOpen = isWeekday && total >= (9 * 60 + 15) && total < (15 * 60 + 30);

        if (marketStatusBadge) {{
          marketStatusBadge.className = `tv-market-badge ${{isOpen ? 'open' : 'closed'}}`;
        }}
        if (marketStatusText) {{
          marketStatusText.textContent = isOpen ? 'MARKET OPEN' : 'MARKET CLOSED';
        }}
        if (marketStatusSub) {{
          marketStatusSub.textContent = isOpen ? 'Live (Closes 15:30 IST)' : 'Opens today 09:15 AM IST';
        }}
        if (dashMarketStatus) {{
          dashMarketStatus.textContent = isOpen ? 'OPEN (Live)' : 'CLOSED (Opens 09:15 AM IST)';
          dashMarketStatus.style.color = isOpen ? 'var(--tv-bull)' : 'var(--tv-text-muted)';
        }}
      }}
      updateMarketStatusUI();
      setInterval(updateMarketStatusUI, 1000);

      // Render Asset Data
      function renderAsset(key, isInitial = false) {{
        let data = ALL_DATA[key];
        if (!data) {{
          data = ALL_DATA[currentInstrument];
        }}
        if (!data || !data.candles || data.candles.length === 0) return;

        lastCandles = data.candles;
        const lastCandle = data.candles[data.candles.length - 1];
        const prevCandle = data.candles.length > 1 ? data.candles[data.candles.length - 2] : lastCandle;
        const diff = lastCandle.close - prevCandle.close;
        const pct = (diff / prevCandle.close) * 100;

        activeTickerTitle.textContent = data.name;
        activeTimeframeBadge.textContent = (data.timeframe || currentTimeframe).toUpperCase();
        activePrice.textContent = lastCandle.close.toFixed(2);
        priceChange.textContent = `${{diff >= 0 ? '+' : ''}}${{diff.toFixed(2)}} (${{diff >= 0 ? '+' : ''}}${{pct.toFixed(2)}}%)`;
        priceChange.className = `tv-chg-pill ${{diff >= 0 ? 'positive' : 'negative'}}`;

        updateOHLC(lastCandle);

        chart.setChartData({{
          candles: data.candles,
          indicators: data.indicators,
          isInitial: isInitial,
          options: getOverlayOptions()
        }});

        updateDashboard(data.indicators);
      }}

      function updateDashboard(ind) {{
        if (!ind) return;
        const db = ind.dashboard || {{}};

        dashSignal.textContent = db.signal || '--';
        dashIPDA.textContent = db.ipda_phase || '--';
        dashModel.textContent = db.last_model || '--';
        dashCISD.textContent = db.cisd_state || '--';
        dashBullSweep.textContent = db.bull_sweep_active || '--';
        dashBearSweep.textContent = db.bear_sweep_active || '--';
        dashPDHPDL.textContent = db.pdh_pdl || '-- / --';
        dashKZ.textContent = db.in_killzone || '--';
        dashSB.textContent = db.silver_bullet || '--';
        dashHTFBias.textContent = db.htf_bias || '--';

        const rawSig = (db.signal || 'HOLD').split(' ')[0];
        dashSignalBadge.textContent = rawSig;
        dashSignalBadge.className = `tv-pine-badge ${{rawSig === 'BUY' ? 'buy' : rawSig === 'SELL' ? 'sell' : 'hold'}}`;

        // Active Setups Count
        const activeFvgs = (ind.fvg_zones || []).filter(f => !f.mitigated && !f.excluded_fake).length;
        const activeObs = (ind.order_blocks || []).filter(o => !o.mitigated).length;
        const activeLiq = (ind.liquidity_levels || []).length;
        if (dashSetupsCount) {{
          dashSetupsCount.textContent = `${{activeFvgs}} FVGs | ${{activeObs}} OBs | ${{activeLiq}} Liq`;
        }}

        // Active Trade & Targets
        if (ind.active_trade) {{
          const at = ind.active_trade;
          if (dashTradeEntry) {{
            dashTradeEntry.textContent = `${{at.signal}} @ ${{at.entry_price.toFixed(2)}}`;
            dashTradeEntry.style.color = at.signal === 'BUY' ? 'var(--tv-bull)' : 'var(--tv-bear)';
          }}
          if (dashTradeTargets) {{
            dashTradeTargets.textContent = `SL: ${{at.sl_price.toFixed(2)}} | TP: ${{at.tp_price.toFixed(2)}}`;
          }}
        }} else if (ind.signals && ind.signals.length > 0) {{
          const latestSig = ind.signals[ind.signals.length - 1];
          if (dashTradeEntry) {{
            dashTradeEntry.textContent = `${{latestSig.signal}} (${{latestSig.model}}) @ ${{latestSig.entry_price.toFixed(2)}}`;
            dashTradeEntry.style.color = latestSig.signal === 'BUY' ? 'var(--tv-bull)' : 'var(--tv-bear)';
          }}
          if (dashTradeTargets) {{
            dashTradeTargets.textContent = `SL: ${{latestSig.sl_price.toFixed(2)}} | TP: ${{latestSig.tp_price.toFixed(2)}}`;
          }}
        }} else {{
          if (dashTradeEntry) {{
            dashTradeEntry.textContent = 'Waiting for sweep';
            dashTradeEntry.style.color = 'var(--tv-text-muted)';
          }}
          if (dashTradeTargets) {{
            dashTradeTargets.textContent = '-- / --';
          }}
        }}

        // Signals Feed (Bottom Ticker)
        if (ind.signals && ind.signals.length > 0) {{
          signalsFeed.innerHTML = '';
          const recent = ind.signals.slice(-6).reverse();
          for (const s of recent) {{
            const item = document.createElement('span');
            const isBuy = s.signal === 'BUY';
            item.className = `tv-alert-pill ${{isBuy ? 'buy' : 'sell'}}`;
            const timeStr = new Date(s.time * 1000).toLocaleTimeString([], {{ hour: '2-digit', minute: '2-digit' }});
            item.innerHTML = `${{isBuy ? '🟢 BUY' : '🔴 SELL'}} <b>${{s.model}}</b> @ <b>${{s.entry_price.toFixed(2)}}</b> [SL: ${{s.sl_price.toFixed(2)}} | TP: ${{s.tp_price.toFixed(2)}}] • <span style="opacity:0.75;">${{timeStr}}</span>`;
            signalsFeed.appendChild(item);
          }}
        }} else {{
          signalsFeed.innerHTML = '<span class="tv-alert-empty">⚡ Monitoring live order flow for liquidity sweeps, Fair Value Gaps, and Order Blocks...</span>';
        }}
      }}

      // Switcher Events: Indices
      indicesButtons.forEach(btn => {{
        btn.addEventListener('click', () => {{
          indicesButtons.forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          currentInstrument = btn.dataset.symbol;
          currentInstrumentName = btn.textContent.trim();
          renderAsset(getActiveKey(), true);
        }});
      }});

      // Switcher Events: Timeframes (1m, 5m, 15m)
      tfButtons.forEach(btn => {{
        btn.addEventListener('click', () => {{
          tfButtons.forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          currentTimeframe = btn.dataset.tf;
          activeTimeframeBadge.textContent = currentTimeframe.toUpperCase();
          renderAsset(getActiveKey(), false);
        }});
      }});

      [toggleFVG, toggleOB, toggleLiq, toggleSignals].forEach(cb => {{
        if (cb) {{
          cb.addEventListener('change', () => {{
            const data = ALL_DATA[getActiveKey()] || ALL_DATA[currentInstrument];
            if (data) {{
              chart.setChartData({{
                candles: data.candles,
                indicators: data.indicators,
                isInitial: false,
                options: getOverlayOptions()
              }});
            }}
          }});
        }}
      }});

      refreshBtn.addEventListener('click', () => {{
        refreshBtn.style.transform = 'rotate(360deg)';
        setTimeout(() => refreshBtn.style.transform = '', 300);
        window.location.reload();
      }});

      // Initial render with NIFTY 50 5m
      renderAsset(getActiveKey(), true);
    }});
  </script>
</body>
</html>
"""

# Render full-screen TradingView native layout without overflow
components.html(full_html, height=820)
