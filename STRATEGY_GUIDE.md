# Institutional ICT Predictive Engine — Strategy & Execution Guide

This document outlines the complete operational strategy of the **Institutional ICT Predictive Engine**. It details how the engine autonomously scans market order flow, scores trade setups, executes option trades on Zerodha Kite (in Paper Mode), and manages positions like an institutional trading desk.

---

## 1. Core Architecture Overview

```
                          ┌──────────────────────────┐
                          │   Live Data (Upstox WS)  │
                          └─────────────┬────────────┘
                                        │ 5m / 15m Candles
                                        ▼
                          ┌──────────────────────────┐
                          │    ICT Predictive Engine │
                          │  (FVG, IFVG, OB, Sweeps) │
                          └─────────────┬────────────┘
                                        │ Prospective Setups
                                        ▼
    ┌───────────────────────────────────────────────────────────────────────┐
    │              THE AGENT BRAIN: Institutional Confluence Matrix         │
    │  • HTF Bias / DOL (25 pts)        • Model Confluence (25 pts)         │
    │  • Major Liquidity Sweeps (20 pts) • 50% MT / Wick Defense (15 pts)    │
    │  • Killzone Timing (15 pts)       • CISD Alignment (+5 pts)           │
    │                                                                       │
    │   Threshold Filter: Score >= 75 (Grade A / A+ Only)                   │
    └───────────────────────────────────┬───────────────────────────────────┘
                                        │ Approved Signals Only
                                        ▼
                          ┌──────────────────────────┐
                          │     RiskGate (Guardrails) │
                          │  (Daily Loss, BE Pyramids)│
                          └─────────────┬────────────┘
                                        │
                    ┌───────────────────┴───────────────────┐
                    ▼                                       ▼
      ┌──────────────────────────┐            ┌──────────────────────────┐
      │   Zerodha Kite Trader    │            │     Telegram Alerts      │
      │  (Autonomous Paper Exec) │            │  (Grade, Score, Details) │
      └─────────────┬────────────┘            └──────────────────────────┘
                    │ Tick-by-Tick Candle Tracking
                    ▼
      ┌─────────────────────────────────────────────────────┐
      │          Active Institutional Desk Manager          │
      │  • +1.0R Expansion ➔ SL moved to Breakeven (Risk=0) │
      │  • 85–90% Near-TP ➔ Lock in Profit on Stall/Wick    │
      │  • Risk-Free Pyramiding ➔ Stack secondary A+ setups │
      └─────────────────────────────────────────────────────┘
```

---

## 2. Institutional Setup Models

The engine trades 5 battle-tested ICT institutional models:

| Model | Status | Setup Mechanism | Entry Trigger | Target & Invalidation |
| :--- | :--- | :--- | :--- | :--- |
| **Turtle Soup Model** | **ACTIVE (+₹23.6k)** | False breakout raid targeting major liquidity: PDH, PDL, PWH, PWL. | Price wicks past HTF level, prints $\ge 25\%$ rejection wick, closes back inside. | **SL:** Beyond sweep wick.<br>**TP:** Equilibrium / opposite pool. |
| **Silver Bullet Model** | **ACTIVE (+₹14.1k)** | Time-boxed Killzone expansion (10:00–11:00 or 14:00–15:00). | Liquidity sweep $\rightarrow$ MSS $\rightarrow$ Fresh FVG retest. | **Exit:** Time-boxed Killzone end or 2:1 TP. |
| **A+ Unicorn Model** | **ACTIVE (+₹8.2k)** | Highest confluence: Breaker Block overlapping directly with an Inverted FVG. | Price retests overlapping zone during Killzone. | **SL:** Beyond zone boundary.<br>**TP:** 2:1 R:R / Draw on Liquidity. |
| **Inverse FVG Model** | **ACTIVE (+₹7.2k)** | Broken FVG flipped into support/resistance defense. | Price retests inverted gap with rejection wick. | **SL:** Beyond IFVG.<br>**TP:** 2:1 R:R. |
| **Classic 2022 Model** | **ACTIVE (-₹1.5k)** | Standard swing sweep + displacement + FVG/OB retest. | Retest of confirmed Order Block or FVG. | **SL:** Beyond zone.<br>**TP:** 2:1 R:R. |
| **Judas Swing Model** | **DISABLED (-₹35.5k)** | Morning Opening Range trap (09:20–09:50). | Disabled: 5m Nifty morning trends cause fakeout re-expansions. | Toggleable via `config/settings.yaml`. |

---

## 3. The Agent Brain: 5-Pillar Confluence Scoring

Every signal is scored from **0 to 100** before execution:

1. **HTF DOL & Bias Alignment (max 25 pts)**:
   - Aligned with HTF Trend/EMA: **+25 pts**
   - Neutral HTF: **+15 pts**
   - Counter-trend: **0 pts**
2. **Model Tier Confluence (max 25 pts)**:
   - Unicorn Model (Breaker + IFVG): **+25 pts**
   - Judas Swing Trap Reversal: **+23 pts**
   - Turtle Soup False Breakout: **+22 pts**
   - Silver Bullet Displacement: **+20 pts**
   - Classic 2022 Model: **+18 pts**
3. **Liquidity Sweep Significance (max 20 pts)**:
   - Major HTF Sweep (PDH, PDL, PWH, PWL): **+20 pts**
   - Opening Range Trapped Liquidity: **+18 pts**
   - Equal Highs / Lows (EQH / EQL): **+16 pts**
   - Internal Minor Swing: **+10 pts**
4. **Candle Rejection & 50% Mean Threshold (MT) Defense (max 15 pts)**:
   - Midpoint defended + Wick $\ge 30\%$: **+15 pts**
   - Midpoint defended + Wick $\ge 20\%$: **+12 pts**
   - Directional close: **+5 pts**
5. **Killzone Timing (max 15 pts)**:
   - Active Killzone (09:20–10:30 or 13:30–15:00): **+15 pts**
   - Off-hours: **+5 pts**
6. **CISD (Change in State of Delivery) Boost**:
   - Matching active delivery streak: **+5 pts**

### Quality Filter:
- **Grade A+ (85–100 pts)**: Elite Institutional Execution.
- **Grade A (75–84 pts)**: High-Probability Execution.
- **Grade B / C (< 75 pts)**: **Blocked / Discarded**. Only A and A+ trades reach execution.

---

## 4. Human Desk Trade Management (Hands-Off)

Once in a trade, the engine actively manages the position bar-by-bar:

1. **Breakeven Defense (+1.0R Expansion)**:
   - As soon as the position gains +1.0R in profit, the Stop Loss is automatically moved to entry. The trade is now **100% risk-free (Open Risk = ₹0)**.
2. **Proximity Profit Locking (85–90% Near-TP)**:
   - If price reaches 85–90% of TP and forms an adverse rejection wick or absorption candle, the engine immediately closes the trade to lock in profits, preventing winners from turning into losses.
3. **Institutional Pyramiding**:
   - If another setup forms while a trade is open, the engine will only add size (pyramid) **if the primary trade is already protected at Breakeven**. No trade with open risk is ever averaged or pyramided.
4. **Daily Capital Protection**:
   - `RiskGate` enforces a strict daily loss ceiling (`max_daily_loss_inr: 2000`). If hit, trading halts immediately for the day.

---

## 5. UI Features & Chart Display

The Streamlit Web UI (`http://localhost:8501`) gives complete visibility into the engine:
- **Real-Time Candlestick Chart**: Direct WebSocket feed with sub-second price updates.
- **Signal Badges**: Displays direction, model, and score: e.g. `SELL [Turtle Soup Model (PDH)] (A+ 87)`.
- **Target Projections**: Dynamic dotted lines for Entry, SL, and 2:1 TP.
- **Liquidity & Structure Markers**:
  - `PDH`, `PDL`, `PWH`, `PWL` steplines.
  - Mitigated vs. unmitigated FVG (green/red) and IFVG (cyan/magenta) zones.
  - Order Blocks and Breaker Blocks with 50% Mean Threshold dashed lines.
  - `🪤 Judas Swing` and `🐢 Turtle Soup` visual event markers.
- **Live HUD Dashboard**: Real-time signal status, IPDA phase, and active trade metrics.

---

## 6. Multi-Timeframe (MTF) Alignment (15m Narrative + 5m Sniper Execution)

To eliminate fakeouts caused by lower timeframe noise, the engine features built-in **Multi-Timeframe Alignment**:
- **15m Macro Narrative**: Evaluates the macro Order Flow and Draw on Liquidity (DOL). Auto-aggregates 15m bars from 5m candles without lookahead bias.
- **5m Sniper Execution**: Waits for displacement and institutional setups inside Killzones on 5m, but only triggers trades in the direction of the 15m narrative.
- **Asymmetric Liquidity Target Expansion**: Expands take-profit targets to major 15m / Daily Liquidity pools (`PDH`, `PDL`, `PWH`, `PWL`), pushing realized Risk-to-Reward to **3:1–4.5:1**.

### Configuration (`config/settings.yaml`):
```yaml
multi_timeframe:
  enabled: true                       # Enable 15m HTF narrative + 5m sniper entry alignment
  narrative_tf: 15                    # Higher timeframe in minutes for macro trend & DOL (15m)
  entry_tf: 5                         # Lower timeframe in minutes for sniper entries (5m)
  enforce_bias_alignment: true        # If 15m is Bullish, 5m cannot take SELL signals (and vice-versa)
  block_counter_trend: true          # Strictly reject signals fighting the 15m order flow
  target_htf_liquidity: true         # Target 15m/Daily PDH/PDL for asymmetric 3:1+ R:R
  htf_ema_len: 50                     # Period for 15m trend bias calculation
```
