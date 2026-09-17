"""
ICT Predictive Signal Engine
Complete Python implementation of the Pine Script indicator:
"ICT Predictive Signals [Liquidity + FVG + OB]"
"""

import math
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
import zoneinfo

from .models import Candle, SwingPoint, LiquidityLevel, FVG, OrderBlock, SignalResult
from .indicator_math import compute_atr, compute_ema
from .sessions import is_in_session

IST = zoneinfo.ZoneInfo("Asia/Kolkata")


class ICTPredictiveEngine:
    def __init__(self, config: Dict[str, Any]):
        self.cfg = config
        
        # Structure settings
        struct_cfg = config.get("structure", {})
        self.left_bars = struct_cfg.get("left_bars", 5)
        self.right_bars = struct_cfg.get("right_bars", 2)
        
        # Mode settings
        mode_cfg = config.get("mode", {})
        self.confirm_on_close = mode_cfg.get("confirm_on_close", False)
        self.sweep_valid_bars = mode_cfg.get("sweep_valid_bars", 40)
        self.ob_search_bars = mode_cfg.get("ob_search_bars", 15)
        
        # Zones settings
        zones_cfg = config.get("zones", {})
        self.show_fvg = zones_cfg.get("show_fvg", True)
        self.show_ob = zones_cfg.get("show_ob", True)
        self.show_liq = zones_cfg.get("show_liq", True)
        self.max_zones = zones_cfg.get("max_zones", 4)
        
        # HTF Liquidity settings
        htf_cfg = config.get("htf_liquidity", {})
        self.show_pdhl = htf_cfg.get("show_pdhl", True)
        self.show_pwhl = htf_cfg.get("show_pwhl", True)
        self.show_pmhl = htf_cfg.get("show_pmhl", False)
        self.htf_priority_only = htf_cfg.get("htf_priority_only", False)
        
        # Equal Highs / Lows
        eq_cfg = config.get("equal_highs_lows", {})
        self.show_eq = eq_cfg.get("show_eq", True)
        self.eq_tol_pct = eq_cfg.get("eq_tol_pct", 0.05)
        
        # Risk settings
        risk_cfg = config.get("risk", {})
        self.atr_len = risk_cfg.get("atr_len", 14)
        self.atr_buffer_mult = risk_cfg.get("atr_buffer_mult", 0.15)
        self.risk_reward = risk_cfg.get("risk_reward", 2.0)
        
        # OTE settings
        ote_cfg = config.get("ote", {})
        self.use_ote = ote_cfg.get("use_ote", True)
        self.ote_mode = ote_cfg.get("mode", "OTE Zone (62-79%)")
        self.ote_min = ote_cfg.get("ote_min", 0.62)
        self.ote_max = ote_cfg.get("ote_max", 0.79)
        
        # Killzones settings
        kz_cfg = config.get("killzones", {})
        self.use_killzone = kz_cfg.get("use_killzone", True)
        self.killzone1 = kz_cfg.get("killzone1", "09:15-10:30")
        self.killzone2 = kz_cfg.get("killzone2", "13:30-15:00")
        
        # HTF Bias settings
        htf_bias_cfg = config.get("htf_bias", {})
        self.use_htf_bias = htf_bias_cfg.get("use_htf_bias", False)
        self.htf_bias_strict = htf_bias_cfg.get("htf_bias_strict", False)
        self.htf_ema_len = htf_bias_cfg.get("htf_ema_len", 50)
        
        # CISD settings
        cisd_cfg = config.get("cisd", {})
        self.use_cisd = cisd_cfg.get("use_cisd", True)
        self.show_cisd = cisd_cfg.get("show_cisd", True)
        
        # FVG Quality settings
        fvgq_cfg = config.get("fvg_quality", {})
        self.use_fvg_quality = fvgq_cfg.get("use_fvg_quality", True)
        self.min_fvg_tier = fvgq_cfg.get("min_fvg_tier", "Standard+")
        self.consol_body_max_pct = fvgq_cfg.get("consol_body_max_pct", 40.0)
        self.fvg_fail_watch_bars = fvgq_cfg.get("fvg_fail_watch_bars", 3)
        
        # Silver Bullet settings
        sb_cfg = config.get("silver_bullet", {})
        self.use_silver_bullet = sb_cfg.get("use_silver_bullet", True)
        self.sb_use_kz2_too = sb_cfg.get("sb_use_kz2_too", False)
        
        # IPDA settings
        ipda_cfg = config.get("ipda", {})
        self.show_ipda = ipda_cfg.get("show_ipda", True)
        self.consol_lookback = ipda_cfg.get("consol_lookback", 10)
        self.consol_atr_mult = ipda_cfg.get("consol_atr_mult", 1.5)

    def _fvg_tier_rank(self, tier: str) -> int:
        if tier == "Highest Probability":
            return 3
        elif tier == "Higher Probability":
            return 2
        return 1

    def _min_tier_rank(self) -> int:
        if self.min_fvg_tier == "Standard+":
            return 1
        elif self.min_fvg_tier == "Higher+":
            return 2
        elif self.min_fvg_tier == "Highest Only":
            return 3
        return 0

    def _entry_model_name(self, tier: str, zone_type: str, in_kz1: bool) -> str:
        is_htf = any(k in tier for k in ["PDH", "PDL", "PWH", "PWL", "PMH", "PML"])
        is_eq = any(k in tier for k in ["EQH", "EQL"])
        if zone_type == "Breaker" and (is_htf or is_eq):
            return "Unicorn Model"
        elif in_kz1 and zone_type == "FVG":
            return "Silver Bullet Model"
        elif is_htf:
            return "Turtle Soup Model"
        elif zone_type == "OB":
            return "Order Block Model"
        elif zone_type == "Breaker":
            return "Breaker Block Model"
        return "2022 Model"

    def _exit_model_text(self, model: str) -> str:
        if model == "Unicorn Model":
            return "Hold full size to TP - highest conviction (Breaker + strong liquidity)."
        elif model == "Silver Bullet Model":
            return "Time-boxed: exit by end of this Killzone hour even if TP not hit yet."
        elif model == "Turtle Soup Model":
            return "Take 50% off at 1R, trail remainder toward the next HTF liquidity level."
        elif model == "Order Block Model":
            return "Exit at TP; invalidate early if price closes back inside the OB."
        elif model == "Breaker Block Model":
            return "Manage tight - exit early if price closes back through the breaker."
        return "Exit at TP or SL, no partials needed."

    def evaluate(self, candles: List[Candle], htf_candles: Optional[List[Candle]] = None) -> Dict[str, Any]:
        """
        Processes candles sequentially bar-by-bar reproducing Pine Script state progression.
        """
        n = len(candles)
        if n < 5:
            return {"error": "Not enough candles to evaluate ICT model"}

        atr_series = compute_atr(candles, self.atr_len)

        # HTF Bias EMA evaluation
        htf_bias = "NEUTRAL"
        if htf_candles and len(htf_candles) >= self.htf_ema_len:
            htf_closes = [c.close for c in htf_candles]
            htf_emas = compute_ema(htf_closes, self.htf_ema_len)
            if htf_closes[-1] > htf_emas[-1]:
                htf_bias = "BULLISH"
            elif htf_closes[-1] < htf_emas[-1]:
                htf_bias = "BEARISH"

        # Higher Timeframe Daily / Weekly / Monthly levels
        # Group by day, week, month to extract previous period high/low
        daily_highs: Dict[str, float] = {}
        daily_lows: Dict[str, float] = {}
        for c in candles:
            dt = datetime.fromtimestamp(c.timestamp, tz=IST)
            day_key = dt.strftime("%Y-%m-%d")
            daily_highs[day_key] = max(daily_highs.get(day_key, c.high), c.high)
            daily_lows[day_key] = min(daily_lows.get(day_key, c.low), c.low)

        sorted_days = sorted(daily_highs.keys())
        pdh = daily_highs[sorted_days[-2]] if len(sorted_days) >= 2 else None
        pdl = daily_lows[sorted_days[-2]] if len(sorted_days) >= 2 else None

        # State variables
        last_sh: Optional[float] = None
        last_sh_bar: Optional[int] = None
        bos_up_done: bool = False

        last_sl: Optional[float] = None
        last_sl_bar: Optional[int] = None
        bos_down_done: bool = False

        bsl_pool: List[LiquidityLevel] = []
        ssl_pool: List[LiquidityLevel] = []

        ob_bull_list: List[OrderBlock] = []
        ob_bear_list: List[OrderBlock] = []

        fvg_bull_list: List[FVG] = []
        fvg_bear_list: List[FVG] = []

        # CISD state
        streak_len = 0
        streak_bull: Optional[bool] = None
        streak_origin: Optional[float] = None
        cisd_state = "NEUTRAL"

        # Sweep tracking
        bull_sweep_level: Optional[float] = None
        bull_sweep_bar: Optional[int] = None
        bull_sweep_active: bool = False
        bull_signal_fired: bool = False
        bull_sweep_tier: str = "Swing"

        bear_sweep_level: Optional[float] = None
        bear_sweep_bar: Optional[int] = None
        bear_sweep_active: bool = False
        bear_signal_fired: bool = False
        bear_sweep_tier: str = "Swing"

        pdh_swept = False
        pdl_swept = False

        # Silver bullet state
        sb_direction = ""
        sb_sweep_bar: Optional[int] = None
        sb_mss_done = False
        sb_fvg_box: Optional[FVG] = None
        sb_signal_fired = False
        sb_sl_price: Optional[float] = None
        sb_tp_price: Optional[float] = None
        sb_trade_state = "NONE"
        prev_in_sb_window = False

        # Signal results
        signals: List[Dict[str, Any]] = []
        silver_bullet_events: List[Dict[str, Any]] = []

        bias_state = "NEUTRAL"
        current_signal = "HOLD"
        entry_price: Optional[float] = None
        sl_price: Optional[float] = None
        tp_price: Optional[float] = None
        last_entry_model = "--"

        market_phase = "Consolidation"
        last_bos_up_bar: Optional[int] = None
        last_bos_down_bar: Optional[int] = None

        # Iterate bar by bar
        for bar_idx in range(n):
            c = candles[bar_idx]
            dt = datetime.fromtimestamp(c.timestamp, tz=IST)
            atr_val = atr_series[bar_idx]

            in_kz1 = is_in_session(dt, self.killzone1)
            in_kz2 = is_in_session(dt, self.killzone2)
            in_killzone = not self.use_killzone or in_kz1 or in_kz2
            in_sb_window = in_kz1 or (self.sb_use_kz2_too and in_kz2)

            # ----------------------------------------------------
            # 1. SWINGS EVALUATION (pivothigh / pivotlow)
            # ----------------------------------------------------
            pivot_idx = bar_idx - self.right_bars
            if pivot_idx >= self.left_bars:
                # Check Pivot High
                target_high = candles[pivot_idx].high
                is_phigh = True
                for k in range(pivot_idx - self.left_bars, bar_idx + 1):
                    if k != pivot_idx and candles[k].high >= target_high:
                        is_phigh = False
                        break
                if is_phigh:
                    last_sh = target_high
                    last_sh_bar = pivot_idx
                    bos_up_done = False
                    
                    # Equal Highs check
                    is_eqh = False
                    if self.show_eq and len(bsl_pool) > 0:
                        tol = target_high * self.eq_tol_pct / 100.0
                        for existing_bsl in bsl_pool:
                            if abs(target_high - existing_bsl.price) <= tol:
                                is_eqh = True
                                break
                    
                    if self.show_liq:
                        bsl_pool.append(LiquidityLevel(price=target_high, bar_index=pivot_idx, tier="EQH" if is_eqh else "BSL", is_eq=is_eqh))
                        if len(bsl_pool) > self.max_zones:
                            bsl_pool.pop(0)

                # Check Pivot Low
                target_low = candles[pivot_idx].low
                is_plow = True
                for k in range(pivot_idx - self.left_bars, bar_idx + 1):
                    if k != pivot_idx and candles[k].low <= target_low:
                        is_plow = False
                        break
                if is_plow:
                    last_sl = target_low
                    last_sl_bar = pivot_idx
                    bos_down_done = False
                    
                    # Equal Lows check
                    is_eql = False
                    if self.show_eq and len(ssl_pool) > 0:
                        tol2 = target_low * self.eq_tol_pct / 100.0
                        for existing_ssl in ssl_pool:
                            if abs(target_low - existing_ssl.price) <= tol2:
                                is_eql = True
                                break
                    
                    if self.show_liq:
                        ssl_pool.append(LiquidityLevel(price=target_low, bar_index=pivot_idx, tier="EQL" if is_eql else "SSL", is_eq=is_eql))
                        if len(ssl_pool) > self.max_zones:
                            ssl_pool.pop(0)

            # ----------------------------------------------------
            # 2. FAIR VALUE GAPS (FVG)
            # ----------------------------------------------------
            if bar_idx >= 2 and self.show_fvg:
                c1 = candles[bar_idx - 2]
                c2 = candles[bar_idx - 1]
                c3 = candles[bar_idx]

                # Bullish FVG: low > high[2]
                if c3.low > c1.high:
                    fvg_top = c3.low
                    fvg_bot = c1.high
                    c3_range = c3.high - c3.low
                    c3_body_pct = (abs(c3.close - c3.open) / c3_range * 100.0) if c3_range > 0 else 100.0
                    c3_consol = c3_body_pct <= self.consol_body_max_pct
                    
                    # Confluence check with active OBs or Liquidity
                    has_conf = False
                    for ob in ob_bull_list + ob_bear_list:
                        if not (ob.top < fvg_bot or ob.bottom > fvg_top):
                            has_conf = True
                            break
                    if not has_conf:
                        for lq in bsl_pool + ssl_pool:
                            if fvg_bot <= lq.price <= fvg_top:
                                has_conf = True
                                break
                    
                    tier = "Highest Probability" if (c3_consol and has_conf) else "Higher Probability" if (c3_consol or has_conf) else "Standard"
                    fvg_item = FVG(top=fvg_top, bottom=fvg_bot, bar_index=bar_idx, is_bullish=True, tier=tier, c3_consolidating=c3_consol, has_confluence=has_conf, c1_high=c1.high, c1_low=c1.low, c3_high=c3.high, c3_low=c3.low)
                    fvg_bull_list.append(fvg_item)
                    if len(fvg_bull_list) > self.max_zones:
                        fvg_bull_list.pop(0)

                # Bearish FVG: high < low[2]
                if c3.high < c1.low:
                    fvg_top = c1.low
                    fvg_bot = c3.high
                    c3_range = c3.high - c3.low
                    c3_body_pct = (abs(c3.close - c3.open) / c3_range * 100.0) if c3_range > 0 else 100.0
                    c3_consol = c3_body_pct <= self.consol_body_max_pct
                    
                    has_conf2 = False
                    for ob in ob_bull_list + ob_bear_list:
                        if not (ob.top < fvg_bot or ob.bottom > fvg_top):
                            has_conf2 = True
                            break
                    if not has_conf2:
                        for lq in bsl_pool + ssl_pool:
                            if fvg_bot <= lq.price <= fvg_top:
                                has_conf2 = True
                                break
                    
                    tier2 = "Highest Probability" if (c3_consol and has_conf2) else "Higher Probability" if (c3_consol or has_conf2) else "Standard"
                    fvg_item2 = FVG(top=fvg_top, bottom=fvg_bot, bar_index=bar_idx, is_bullish=False, tier=tier2, c3_consolidating=c3_consol, has_confluence=has_conf2, c1_high=c1.high, c1_low=c1.low, c3_high=c3.high, c3_low=c3.low)
                    fvg_bear_list.append(fvg_item2)
                    if len(fvg_bear_list) > self.max_zones:
                        fvg_bear_list.pop(0)

            # FVG Mitigation + CE early failure
            for f in fvg_bull_list:
                ce = (f.top + f.bottom) / 2.0
                if c.close < f.bottom:
                    f.mitigated = True
                    f.mitigated_bar = bar_idx
                elif self.use_fvg_quality and not f.excluded_fake and (bar_idx - f.bar_index) <= self.fvg_fail_watch_bars and c.close < ce:
                    f.excluded_fake = True

            for f in fvg_bear_list:
                ce = (f.top + f.bottom) / 2.0
                if c.close > f.top:
                    f.mitigated = True
                    f.mitigated_bar = bar_idx
                elif self.use_fvg_quality and not f.excluded_fake and (bar_idx - f.bar_index) <= self.fvg_fail_watch_bars and c.close > ce:
                    f.excluded_fake = True

            # ----------------------------------------------------
            # 3. ORDER BLOCKS (OB) & BREAKERS
            # ----------------------------------------------------
            # Bullish BOS: close > last_sh
            if last_sh is not None and c.close > last_sh and not bos_up_done:
                bos_up_done = True
                last_bos_up_bar = bar_idx
                # Search back for last red candle
                for back_i in range(1, min(self.ob_search_bars + 1, bar_idx)):
                    cand = candles[bar_idx - back_i]
                    if cand.close < cand.open:
                        ob_bull_list.append(OrderBlock(top=cand.high, bottom=cand.low, bar_index=bar_idx - back_i, is_bullish=True))
                        if len(ob_bull_list) > self.max_zones:
                            ob_bull_list.pop(0)
                        break

            # Bearish BOS: close < last_sl
            if last_sl is not None and c.close < last_sl and not bos_down_done:
                bos_down_done = True
                last_bos_down_bar = bar_idx
                # Search back for last green candle
                for back_i in range(1, min(self.ob_search_bars + 1, bar_idx)):
                    cand = candles[bar_idx - back_i]
                    if cand.close > cand.open:
                        ob_bear_list.append(OrderBlock(top=cand.high, bottom=cand.low, bar_index=bar_idx - back_i, is_bullish=False))
                        if len(ob_bear_list) > self.max_zones:
                            ob_bear_list.pop(0)
                        break

            # Mitigation and Breaker Block conversion
            for ob in ob_bull_list:
                if not ob.mitigated and c.close < ob.bottom:
                    ob.mitigated = True
                    ob.mitigated_bar = bar_idx
                    if self.show_ob:
                        ob_bear_list.append(OrderBlock(top=ob.top, bottom=ob.bottom, bar_index=bar_idx, is_bullish=False, is_breaker=True))
                        if len(ob_bear_list) > self.max_zones:
                            ob_bear_list.pop(0)

            for ob in ob_bear_list:
                if not ob.mitigated and c.close > ob.top:
                    ob.mitigated = True
                    ob.mitigated_bar = bar_idx
                    if self.show_ob:
                        ob_bull_list.append(OrderBlock(top=ob.top, bottom=ob.bottom, bar_index=bar_idx, is_bullish=True, is_breaker=True))
                        if len(ob_bull_list) > self.max_zones:
                            ob_bull_list.pop(0)

            # ----------------------------------------------------
            # 3b. CISD (Change in State of Delivery)
            # ----------------------------------------------------
            if bar_idx >= 1:
                prev_c = candles[bar_idx - 1]
                prev_bull = prev_c.close > prev_c.open
                prev_bear = prev_c.close < prev_c.open
                if prev_bull or prev_bear:
                    if streak_bull is None:
                        streak_bull = prev_bull
                        streak_origin = prev_c.open
                        streak_len = 1
                    elif prev_bull == streak_bull:
                        streak_len += 1
                    else:
                        streak_bull = prev_bull
                        streak_origin = prev_c.open
                        streak_len = 1

                cisd_bullish = (streak_origin is not None and streak_bull is False and c.close > streak_origin)
                cisd_bearish = (streak_origin is not None and streak_bull is True and c.close < streak_origin)

                if cisd_bullish:
                    cisd_state = "BULLISH"
                elif cisd_bearish:
                    cisd_state = "BEARISH"

            # ----------------------------------------------------
            # 4. LIQUIDITY SWEEPS
            # ----------------------------------------------------
            eval_bar = not self.confirm_on_close or (bar_idx == n - 1)

            # Swing sweeps
            if eval_bar and not self.htf_priority_only:
                # Sell-side sweep (low wicks below SSL and closes back above)
                for idx_s in range(len(ssl_pool) - 1, -1, -1):
                    ssl = ssl_pool[idx_s]
                    if c.low < ssl.price and c.close > ssl.price:
                        bull_sweep_level = ssl.price
                        bull_sweep_bar = bar_idx
                        bull_sweep_active = True
                        bull_signal_fired = False
                        bull_sweep_tier = "EQL (Equal Lows)" if ssl.is_eq else "Swing"
                        ssl_pool.pop(idx_s)
                        break

                # Buy-side sweep (high wicks above BSL and closes back below)
                for idx_b in range(len(bsl_pool) - 1, -1, -1):
                    bsl = bsl_pool[idx_b]
                    if c.high > bsl.price and c.close < bsl.price:
                        bear_sweep_level = bsl.price
                        bear_sweep_bar = bar_idx
                        bear_sweep_active = True
                        bear_signal_fired = False
                        bear_sweep_tier = "EQH (Equal Highs)" if bsl.is_eq else "Swing"
                        bsl_pool.pop(idx_b)
                        break

            # HTF sweeps (PDL / PDH)
            if eval_bar and pdl is not None and not pdl_swept:
                if c.low < pdl and c.close > pdl:
                    bull_sweep_level = pdl
                    bull_sweep_bar = bar_idx
                    bull_sweep_active = True
                    bull_signal_fired = False
                    bull_sweep_tier = "PDL (Daily Liquidity)"
                    pdl_swept = True

            if eval_bar and pdh is not None and not pdh_swept:
                if c.high > pdh and c.close < pdh:
                    bear_sweep_level = pdh
                    bear_sweep_bar = bar_idx
                    bear_sweep_active = True
                    bear_signal_fired = False
                    bear_sweep_tier = "PDH (Daily Liquidity)"
                    pdh_swept = True

            # Expire stale sweeps
            if bull_sweep_active and bull_sweep_bar is not None and (bar_idx - bull_sweep_bar > self.sweep_valid_bars):
                bull_sweep_active = False
            if bear_sweep_active and bear_sweep_bar is not None and (bar_idx - bear_sweep_bar > self.sweep_valid_bars):
                bear_sweep_active = False

            # ----------------------------------------------------
            # 4b. DEDICATED SILVER BULLET MODEL
            # ----------------------------------------------------
            if self.use_silver_bullet:
                if in_sb_window and not prev_in_sb_window:
                    # New window starts
                    sb_direction = ""
                    sb_sweep_bar = None
                    sb_mss_done = False
                    sb_fvg_box = None
                    sb_signal_fired = False

                if in_sb_window and not sb_signal_fired:
                    # Step 1: sweep happening inside window
                    if sb_sweep_bar is None:
                        if bull_sweep_bar == bar_idx:
                            sb_direction = "BULLISH"
                            sb_sweep_bar = bar_idx
                        elif bear_sweep_bar == bar_idx:
                            sb_direction = "BEARISH"
                            sb_sweep_bar = bar_idx
                    # Step 2: MSS after sweep
                    elif not sb_mss_done:
                        if sb_direction == "BULLISH" and last_bos_up_bar is not None and last_bos_up_bar >= sb_sweep_bar:
                            sb_mss_done = True
                        elif sb_direction == "BEARISH" and last_bos_down_bar is not None and last_bos_down_bar >= sb_sweep_bar:
                            sb_mss_done = True
                    # Step 3: Fresh FVG forming after MSS
                    elif sb_fvg_box is None:
                        if sb_direction == "BULLISH" and len(fvg_bull_list) > 0:
                            last_fvg = fvg_bull_list[-1]
                            if last_fvg.bar_index > sb_sweep_bar and (last_bos_up_bar is None or last_fvg.bar_index >= last_bos_up_bar):
                                sb_fvg_box = last_fvg
                        elif sb_direction == "BEARISH" and len(fvg_bear_list) > 0:
                            last_fvg2 = fvg_bear_list[-1]
                            if last_fvg2.bar_index > sb_sweep_bar and (last_bos_down_bar is None or last_fvg2.bar_index >= last_bos_down_bar):
                                sb_fvg_box = last_fvg2

                # Step 4: Retracement into fresh FVG
                if in_sb_window and not sb_signal_fired and sb_fvg_box is not None:
                    if c.low <= sb_fvg_box.top and c.high >= sb_fvg_box.bottom:
                        sb_signal_fired = True
                        if sb_direction == "BULLISH":
                            sb_sl_price = float(round(sb_fvg_box.bottom - atr_val * self.atr_buffer_mult, 2))
                            sb_tp_price = float(round(c.close + (c.close - sb_sl_price) * self.risk_reward, 2))
                            sb_trade_state = "LONG_OPEN"
                            silver_bullet_events.append({
                                "type": "SILVER_BULLET_BUY",
                                "bar_index": bar_idx,
                                "time": c.timestamp,
                                "price": c.close,
                                "sl": sb_sl_price,
                                "tp": sb_tp_price,
                                "exit_plan": "Time-boxed: exit by end of Killzone hour"
                            })
                        else:
                            sb_sl_price = float(round(sb_fvg_box.top + atr_val * self.atr_buffer_mult, 2))
                            sb_tp_price = float(round(c.close - (sb_sl_price - c.close) * self.risk_reward, 2))
                            sb_trade_state = "SHORT_OPEN"
                            silver_bullet_events.append({
                                "type": "SILVER_BULLET_SELL",
                                "bar_index": bar_idx,
                                "time": c.timestamp,
                                "price": c.close,
                                "sl": sb_sl_price,
                                "tp": sb_tp_price,
                                "exit_plan": "Time-boxed: exit by end of Killzone hour"
                            })

                # Check Silver Bullet trade closure
                if sb_trade_state == "LONG_OPEN":
                    if c.high >= sb_tp_price:
                        silver_bullet_events.append({"type": "TP_HIT", "bar_index": bar_idx, "time": c.timestamp, "price": sb_tp_price})
                        sb_trade_state = "NONE"
                    elif c.low <= sb_sl_price:
                        silver_bullet_events.append({"type": "SL_HIT", "bar_index": bar_idx, "time": c.timestamp, "price": sb_sl_price})
                        sb_trade_state = "NONE"
                    elif not in_sb_window:
                        silver_bullet_events.append({"type": "TIME_BOXED_EXIT", "bar_index": bar_idx, "time": c.timestamp, "price": c.close})
                        sb_trade_state = "NONE"

                elif sb_trade_state == "SHORT_OPEN":
                    if c.low <= sb_tp_price:
                        silver_bullet_events.append({"type": "TP_HIT", "bar_index": bar_idx, "time": c.timestamp, "price": sb_tp_price})
                        sb_trade_state = "NONE"
                    elif c.high >= sb_sl_price:
                        silver_bullet_events.append({"type": "SL_HIT", "bar_index": bar_idx, "time": c.timestamp, "price": sb_sl_price})
                        sb_trade_state = "NONE"
                    elif not in_sb_window:
                        silver_bullet_events.append({"type": "TIME_BOXED_EXIT", "bar_index": bar_idx, "time": c.timestamp, "price": c.close})
                        sb_trade_state = "NONE"

                prev_in_sb_window = in_sb_window

            # ----------------------------------------------------
            # 5. PREDICTIVE SIGNALS (Sweep + Zone Touch)
            # ----------------------------------------------------
            # OTE / Discount / Premium checks
            ote_range = (last_sh - last_sl) if (last_sh is not None and last_sl is not None) else None
            eq_level = ((last_sh + last_sl) / 2.0) if ote_range is not None else None

            is_discount_ok = True
            if self.use_ote and ote_range is not None:
                if self.ote_mode == "Equilibrium (50%)":
                    is_discount_ok = c.close < eq_level
                else:
                    ote_top = last_sh - ote_range * self.ote_min
                    ote_bottom = last_sh - ote_range * self.ote_max
                    is_discount_ok = (c.close <= ote_top and c.close >= ote_bottom)

            is_premium_ok = True
            if self.use_ote and ote_range is not None:
                if self.ote_mode == "Equilibrium (50%)":
                    is_premium_ok = c.close > eq_level
                else:
                    ote_bottom2 = last_sl + ote_range * self.ote_min
                    ote_top2 = last_sl + ote_range * self.ote_max
                    is_premium_ok = (c.close >= ote_bottom2 and c.close <= ote_top2)

            is_htf_ok_buy = not self.use_htf_bias or (htf_bias == "BULLISH" or (not self.htf_bias_strict and htf_bias == "NEUTRAL"))
            is_htf_ok_sell = not self.use_htf_bias or (htf_bias == "BEARISH" or (not self.htf_bias_strict and htf_bias == "NEUTRAL"))

            buy_signal = False
            sell_signal = False

            # BUY evaluation
            if eval_bar and in_killzone and is_discount_ok and (not self.use_cisd or cisd_state == "BULLISH") and is_htf_ok_buy and bull_sweep_active and not bull_signal_fired:
                zone_top = None
                zone_bot = None
                zone_type = ""
                # Check Bullish FVGs
                for fvg in reversed(fvg_bull_list):
                    if not fvg.mitigated and (not self.use_fvg_quality or (not fvg.excluded_fake and self._fvg_tier_rank(fvg.tier) >= self._min_tier_rank())):
                        if c.low <= fvg.top and c.high >= fvg.bottom:
                            zone_top = fvg.top
                            zone_bot = fvg.bottom
                            zone_type = "FVG"
                            break
                # Check Bullish OBs if no FVG touched
                if zone_top is None:
                    for ob in reversed(ob_bull_list):
                        if not ob.mitigated and c.low <= ob.top and c.high >= ob.bottom:
                            zone_top = ob.top
                            zone_bot = ob.bottom
                            zone_type = "Breaker" if ob.is_breaker else "OB"
                            break

                if zone_top is not None:
                    entry_price = c.close
                    sl_price = float(round(min(zone_bot, bull_sweep_level or zone_bot) - atr_val * self.atr_buffer_mult, 2))
                    tp_price = float(round(entry_price + (entry_price - sl_price) * self.risk_reward, 2))
                    buy_signal = True
                    bull_signal_fired = True
                    bull_sweep_active = False
                    current_signal = "BUY"
                    last_entry_model = self._entry_model_name(bull_sweep_tier, zone_type, in_kz1)
                    bias_state = "BULLISH"

                    signals.append({
                        "signal": "BUY",
                        "bar_index": bar_idx,
                        "time": c.timestamp,
                        "entry_price": entry_price,
                        "sl_price": sl_price,
                        "tp_price": tp_price,
                        "tier": bull_sweep_tier,
                        "model": last_entry_model,
                        "exit_plan": self._exit_model_text(last_entry_model),
                        "cisd": cisd_state
                    })

            # SELL evaluation
            if eval_bar and in_killzone and is_premium_ok and (not self.use_cisd or cisd_state == "BEARISH") and is_htf_ok_sell and bear_sweep_active and not bear_signal_fired:
                zone_top_b = None
                zone_bot_b = None
                zone_type_b = ""
                # Check Bearish FVGs
                for fvg in reversed(fvg_bear_list):
                    if not fvg.mitigated and (not self.use_fvg_quality or (not fvg.excluded_fake and self._fvg_tier_rank(fvg.tier) >= self._min_tier_rank())):
                        if c.low <= fvg.top and c.high >= fvg.bottom:
                            zone_top_b = fvg.top
                            zone_bot_b = fvg.bottom
                            zone_type_b = "FVG"
                            break
                # Check Bearish OBs
                if zone_top_b is None:
                    for ob in reversed(ob_bear_list):
                        if not ob.mitigated and c.low <= ob.top and c.high >= ob.bottom:
                            zone_top_b = ob.top
                            zone_bot_b = ob.bottom
                            zone_type_b = "Breaker" if ob.is_breaker else "OB"
                            break

                if zone_top_b is not None:
                    entry_price = c.close
                    sl_price = float(round(max(zone_top_b, bear_sweep_level or zone_top_b) + atr_val * self.atr_buffer_mult, 2))
                    tp_price = float(round(entry_price - (sl_price - entry_price) * self.risk_reward, 2))
                    sell_signal = True
                    bear_signal_fired = True
                    bear_sweep_active = False
                    current_signal = "SELL"
                    last_entry_model = self._entry_model_name(bear_sweep_tier, zone_type_b, in_kz1)
                    bias_state = "BEARISH"

                    signals.append({
                        "signal": "SELL",
                        "bar_index": bar_idx,
                        "time": c.timestamp,
                        "entry_price": entry_price,
                        "sl_price": sl_price,
                        "tp_price": tp_price,
                        "tier": bear_sweep_tier,
                        "model": last_entry_model,
                        "exit_plan": self._exit_model_text(last_entry_model),
                        "cisd": cisd_state
                    })

            # Bias ribbon reset on SL/TP hit
            if bias_state == "BULLISH" and sl_price is not None and tp_price is not None:
                if c.low <= sl_price or c.high >= tp_price:
                    bias_state = "NEUTRAL"
            elif bias_state == "BEARISH" and sl_price is not None and tp_price is not None:
                if c.high >= sl_price or c.low <= tp_price:
                    bias_state = "NEUTRAL"

            # ----------------------------------------------------
            # 5c. IPDA MARKET PHASE
            # ----------------------------------------------------
            consol_slice = candles[max(0, bar_idx - self.consol_lookback + 1):bar_idx + 1]
            consol_range = max(x.high for x in consol_slice) - min(x.low for x in consol_slice)
            is_consolidating = consol_range < atr_val * self.consol_atr_mult

            fresh_bos_up = (last_bos_up_bar == bar_idx)
            fresh_bos_down = (last_bos_down_bar == bar_idx)
            fresh_bull_sweep = (bull_sweep_bar == bar_idx)
            fresh_bear_sweep = (bear_sweep_bar == bar_idx)

            if fresh_bos_up:
                market_phase = "Expansion (Bullish)"
            elif fresh_bos_down:
                market_phase = "Expansion (Bearish)"
            elif buy_signal:
                market_phase = "Retracement (Bullish)" if "Bullish" in market_phase else "Reversal (Bullish)"
            elif sell_signal:
                market_phase = "Retracement (Bearish)" if "Bearish" in market_phase else "Reversal (Bearish)"
            elif fresh_bear_sweep and "Bullish" in market_phase:
                market_phase = "Reversal (Bearish)"
            elif fresh_bull_sweep and "Bearish" in market_phase:
                market_phase = "Reversal (Bullish)"
            elif is_consolidating and not fresh_bos_up and not fresh_bos_down:
                market_phase = "Consolidation"

        # Construct payload for UI & Dashboard
        current_candle = candles[-1]
        dt_last = datetime.fromtimestamp(current_candle.timestamp, tz=IST)
        in_kz_now = not self.use_killzone or is_in_session(dt_last, self.killzone1) or is_in_session(dt_last, self.killzone2)

        sb_status = (
            "disabled" if not self.use_silver_bullet
            else f"trade open ({sb_trade_state})" if sb_trade_state != "NONE"
            else "outside window" if not is_in_session(dt_last, self.killzone1)
            else "fired this window" if sb_signal_fired
            else "waiting for sweep" if sb_sweep_bar is None
            else "sweep done, waiting for MSS" if not sb_mss_done
            else "MSS done, waiting for fresh FVG" if sb_fvg_box is None
            else "watching for retracement into FVG"
        )

        dashboard = {
            "signal": "BUY (in play)" if bias_state == "BULLISH" else "SELL (in play)" if bias_state == "BEARISH" else "HOLD (waiting)",
            "ipda_phase": market_phase,
            "last_model": last_entry_model,
            "cisd_state": f"{cisd_state} ({'required' if self.use_cisd else 'info only'})",
            "bull_sweep_active": f"YES ({bull_sweep_tier})" if bull_sweep_active else "no",
            "bear_sweep_active": f"YES ({bear_sweep_tier})" if bear_sweep_active else "no",
            "mode": "Confirmed" if self.confirm_on_close else "Live/Predictive",
            "pdh_pdl": f"{f'{pdh:.2f}' if pdh else '--'} / {f'{pdl:.2f}' if pdl else '--'}",
            "in_killzone": "YES" if in_kz_now else "no",
            "htf_priority_only": "ON" if self.htf_priority_only else "off",
            "silver_bullet": sb_status,
            "htf_bias": f"{htf_bias} ({'active' if self.use_htf_bias else 'off'})",
            "bias_state": bias_state
        }

        # Serialized zones for frontend rendering
        fvg_payload = [
            {
                "top": f.top,
                "bottom": f.bottom,
                "start_bar": max(0, f.bar_index - 2),
                "end_bar": min(n - 1, f.bar_index + 20),
                "bar_index": f.bar_index,
                "time": candles[f.bar_index].timestamp if f.bar_index < n else 0,
                "is_bullish": f.is_bullish,
                "tier": f.tier,
                "mitigated": f.mitigated,
                "excluded_fake": f.excluded_fake,
                "c1_high": f.c1_high,
                "c1_low": f.c1_low,
                "c3_high": f.c3_high,
                "c3_low": f.c3_low
            }
            for f in (fvg_bull_list + fvg_bear_list)
        ]

        ob_payload = [
            {
                "top": ob.top,
                "bottom": ob.bottom,
                "start_bar": ob.bar_index,
                "end_bar": min(n - 1, ob.bar_index + 20),
                "bar_index": ob.bar_index,
                "time": candles[ob.bar_index].timestamp if ob.bar_index < n else 0,
                "is_bullish": ob.is_bullish,
                "is_breaker": ob.is_breaker,
                "mitigated": ob.mitigated
            }
            for ob in (ob_bull_list + ob_bear_list)
        ]

        liquidity_payload = [
            {
                "price": lq.price,
                "start_bar": lq.bar_index,
                "end_bar": min(n - 1, lq.bar_index + 20),
                "bar_index": lq.bar_index,
                "time": candles[lq.bar_index].timestamp if lq.bar_index < n else 0,
                "tier": lq.tier,
                "is_eq": lq.is_eq
            }
            for lq in (bsl_pool + ssl_pool)
        ]

        return {
            "dashboard": dashboard,
            "signals": signals,
            "silver_bullet_events": silver_bullet_events,
            "fvg_zones": fvg_payload,
            "order_blocks": ob_payload,
            "liquidity_levels": liquidity_payload,
            "pdh": pdh,
            "pdl": pdl,
            "active_trade": {
                "entry_price": entry_price,
                "sl_price": sl_price,
                "tp_price": tp_price,
                "signal": current_signal,
                "bias": bias_state
            } if bias_state != "NEUTRAL" else None
        }
