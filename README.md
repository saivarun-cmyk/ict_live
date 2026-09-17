# ⚡ ICT Predictive Signals Engine (Real-Time Live Charting System)

A standalone real-time trading engine and interactive web charting terminal replicating your custom Pine Script indicator: **"ICT Predictive Signals [Liquidity + FVG + OB]"**.

---

## 🎯 Target Instruments

- **Indices (Default)**:
  - **NIFTY 50** (`NSE_INDEX|Nifty 50`)
  - **BANK NIFTY** (`NSE_INDEX|Nifty Bank`)
  - **SENSEX** (`BSE_INDEX|SENSEX`)
- **Configurable Equities**:
  - Add or toggle any stock in `config/instruments.yaml` (e.g. RELIANCE, HDFCBANK, TCS, INFY, ICICIBANK).

---

## 🚀 Quick Start

### 1. Launch the Engine
Run the one-click startup script:
```bash
./run.sh
```

### 2. Open the Web Terminal
Open your browser and navigate to:
```
http://localhost:8000
```

---

## 🧠 Indicator Features (1:1 Pine Script Port)

1. **Structure / Swings**: Evaluates pivot highs & pivot lows with configurable `left_bars=5` and `right_bars=2`.
2. **Equal Highs / Lows (EQH/EQL)**: Clusters swing points within 0.05% tolerance into high-probability liquidity pools.
3. **Higher Timeframe Liquidity**: Automatically calculates Previous Day High/Low (PDH/PDL), Previous Week (PWH/PWL), and Previous Month (PMH/PML).
4. **Fair Value Gaps (FVG) with Quality Scoring**:
   - Scores each 3-candle imbalance as *Standard*, *Higher Probability*, or *Highest Probability* based on 3rd-candle consolidation ratio.
   - Detects confluence with Order Blocks and Liquidity pools.
   - Filters early CE (Consequent Encroachment) midpoint failures to prevent fake FVGs.
5. **Order Blocks & Breaker Blocks**:
   - Identifies last opposite-colored candle before a Break of Structure (BOS).
   - Converts mitigated Order Blocks into dynamic Breakers.
6. **CISD (Change in State of Delivery)**: Tracks runs of consecutive candle closes and confirms delivery direction flip upon crossing the origin open.
7. **Premium / Discount (OTE)**: Filters BUYs strictly to discount and SELLs to premium zones.
8. **Killzones (IST)**:
   - Opening Killzone: 09:15 - 10:30 IST
   - Afternoon Killzone: 13:30 - 15:00 IST
9. **Dedicated Silver Bullet Model**: Sweep ➔ MSS ➔ Fresh FVG ➔ Retracement inside Killzone with automatic SL/TP and time-boxed exit.
10. **Telegram Alerts**: Rich HTML notifications matching Pine Script alert messages.

---

## ⚙️ Upstox & Telegram Configuration

Edit `.env`:
```ini
# Upstox API v2 Credentials (optional - uses realistic simulator if blank)
UPSTOX_API_KEY=your_api_key
UPSTOX_API_SECRET=your_api_secret
UPSTOX_ACCESS_TOKEN=your_access_token

# Telegram Notifications
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```
