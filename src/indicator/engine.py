"""
ICT Predictive Signal Engine
Complete Python implementation of the Pine Script indicator:
"ICT Predictive Signals [Liquidity + FVG + OB]"
"""

import math
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
import zoneinfo

from .models import Candle, SwingPoint, LiquidityLevel, FVG, OrderBlock, SignalResult, JudasSwingEvent, TurtleSoupEvent
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
        self.use_killzone    = kz_cfg.get("use_killzone", True)
        self.killzone1       = kz_cfg.get("killzone1", "09:20-10:30")
        self.killzone2       = kz_cfg.get("killzone2", "13:30-15:00")
        self.skip_open_bar   = kz_cfg.get("skip_open_bar", True)   # Block the 09:15 candle
        self.strict_killzone = kz_cfg.get("strict_killzone", True)  # No OOK signals
        
        # Multi-Timeframe (MTF) settings
        mtf_cfg = config.get("multi_timeframe", {})
        self.use_mtf = mtf_cfg.get("enabled", False)
        self.mtf_narrative_tf = int(mtf_cfg.get("narrative_tf", 15))
        self.mtf_entry_tf = int(mtf_cfg.get("entry_tf", 5))
        self.mtf_enforce_bias = mtf_cfg.get("enforce_bias_alignment", True)
        self.mtf_block_counter = mtf_cfg.get("block_counter_trend", True)
        self.mtf_target_htf = mtf_cfg.get("target_htf_liquidity", True)

        # HTF Bias settings
        htf_bias_cfg = config.get("htf_bias", {})
        self.use_htf_bias = htf_bias_cfg.get("use_htf_bias", self.use_mtf)
        self.htf_bias_strict = htf_bias_cfg.get("htf_bias_strict", False)
        self.htf_ema_len = int(mtf_cfg.get("htf_ema_len", htf_bias_cfg.get("htf_ema_len", 50)))
        
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

        # Traditional ICT settings (strict OB validation, FVG quality, setup chaining, confirmed rejection)
        trad_cfg = config.get("traditional_ict")
        if trad_cfg is None:
            trad_cfg = config.get("traditionalICT", {})

        if isinstance(trad_cfg, bool):
            self.traditional_ict = trad_cfg
            self.trad_require_sweep = trad_cfg
            self.trad_require_fvg = trad_cfg
            self.trad_require_rejection = trad_cfg
            self.trad_min_wick_pct = 20.0
            self.trad_respect_mean_threshold = True
            self.trad_max_setup_bars = 25
            self.use_ifvg = True
        elif isinstance(trad_cfg, dict):
            self.traditional_ict = trad_cfg.get("enabled", trad_cfg.get("traditionalICT", False))
            self.trad_require_sweep = trad_cfg.get("require_liquidity_sweep", True)
            self.trad_require_fvg = trad_cfg.get("require_displacement_fvg", True)
            self.trad_require_rejection = trad_cfg.get("require_rejection_candle", True)
            self.trad_min_wick_pct = float(trad_cfg.get("min_rejection_wick_pct", 20.0))
            self.trad_respect_mean_threshold = trad_cfg.get("respect_mean_threshold", True)
            self.trad_max_setup_bars = int(trad_cfg.get("max_setup_bars", 25))
            self.use_ifvg = trad_cfg.get("use_ifvg", True)
        else:
            self.traditional_ict = False
            self.trad_require_sweep = False
            self.trad_require_fvg = False
            self.trad_require_rejection = False
            self.trad_min_wick_pct = 20.0
            self.trad_respect_mean_threshold = False
            self.trad_max_setup_bars = 25
            self.use_ifvg = zones_cfg.get("use_ifvg", True)

        # Judas Swing settings
        js_cfg = config.get("judas_swing", {})
        self.use_judas_swing = js_cfg.get("enabled", True)
        self.judas_window = js_cfg.get("window", "09:20-09:50")
        self.judas_opening_bars = int(js_cfg.get("opening_range_bars", 1))

        # Turtle Soup settings
        ts_cfg = config.get("turtle_soup", {})
        self.use_turtle_soup = ts_cfg.get("enabled", True)
        self.ts_targets = ts_cfg.get("sweep_targets", ["PDH", "PDL", "PWH", "PWL"])
        self.ts_min_wick_pct = float(ts_cfg.get("min_rejection_wick_pct", 25.0))
        self.ts_require_close_inside = ts_cfg.get("require_close_inside", True)

        # Institutional ICT Agent Brain (Confluence Scoring & Quality Grading)
        brain_cfg = config.get("agent_brain", {})
        self.enable_confluence_filter = brain_cfg.get("enable_confluence_filter", True)
        self.min_confluence_score = int(brain_cfg.get("min_confluence_score", 75))

    def _score_signal(
        self,
        signal_dir: str,
        model: str,
        tier: str,
        in_killzone: bool,
        htf_bias: str,
        cisd_state: str,
        wick_pct: float,
        mt_defended: bool,
        is_breaker: bool = False,
        is_ifvg: bool = False
    ) -> Tuple[int, str, List[str]]:
        """
        Institutional ICT Confluence Scoring Engine (The Agent Brain).
        Evaluates setup quality from 0 to 100 based on 5 pillars:
          1. HTF Draw on Liquidity (DOL) & Bias alignment (max 25)
          2. Model Confluence (Unicorn, Judas, Turtle Soup, Silver Bullet) (max 25)
          3. Liquidity Sweep Significance (PDH, PDL, PWH, PWL, EQH, EQL) (max 20)
          4. Candle Rejection & 50% MT/CE Defense (max 15)
          5. Killzone / Session Timing (max 15)
        Returns (score, grade, factors).
        """
        score = 0
        factors = []

        # 1. HTF DOL & Bias Alignment (max 25)
        if (signal_dir == "BUY" and htf_bias == "BULLISH") or (signal_dir == "SELL" and htf_bias == "BEARISH"):
            score += 25
            factors.append(f"HTF Bias Alignment ({htf_bias})")
        elif htf_bias == "NEUTRAL":
            score += 15
            factors.append("Neutral HTF (Intraday Independence)")
        else:
            factors.append(f"Counter-Trend vs HTF ({htf_bias})")

        # 2. Model Confluence Tier (max 25)
        if "Unicorn" in model or (is_breaker and is_ifvg):
            score += 25
            factors.append("A+ Unicorn Model (Breaker + IFVG)")
        elif "Judas Swing" in model:
            score += 23
            factors.append("Judas Swing Trap Reversal")
        elif "Turtle Soup" in model:
            score += 22
            factors.append("Turtle Soup HTF False Breakout")
        elif "Silver Bullet" in model:
            score += 20
            factors.append("Silver Bullet KZ Displacement")
        elif "2022" in model:
            score += 18
            factors.append("Classic 2022 Model")
        else:
            score += 12
            factors.append("Standard Structure Retest")

        # 3. Liquidity Sweep Significance (max 20)
        is_htf_sweep = any(k in tier for k in ["PDH", "PDL", "PWH", "PWL", "PMH", "PML"])
        is_eq_sweep = any(k in tier for k in ["EQH", "EQL"])
        if is_htf_sweep:
            score += 20
            factors.append(f"Major HTF Liquidity Swept ({tier})")
        elif is_eq_sweep:
            score += 16
            factors.append(f"Equal Liquidity Pool Swept ({tier})")
        elif "Opening Range" in tier or "Judas" in model:
            score += 18
            factors.append("Opening Range Trapped Liquidity")
        else:
            score += 10
            factors.append(f"Internal Swing Swept ({tier})")

        # 4. Candle Rejection & 50% MT/CE Defense (max 15)
        if mt_defended and wick_pct >= 30.0:
            score += 15
            factors.append(f"Elite MT Defense (Wick {wick_pct:.0f}%)")
        elif mt_defended and wick_pct >= 20.0:
            score += 12
            factors.append(f"Confirmed MT Defense (Wick {wick_pct:.0f}%)")
        elif wick_pct >= 20.0:
            score += 8
            factors.append(f"Rejection Wick ({wick_pct:.0f}%)")
        else:
            score += 5
            factors.append("Directional Close Defense")

        # 5. Killzone / Session Timing (max 15)
        if in_killzone:
            score += 15
            factors.append("Active ICT Killzone")
        else:
            score += 5
            factors.append("Off-Killzone Timing")

        # CISD extra boost
        if (signal_dir == "BUY" and cisd_state == "BULLISH") or (signal_dir == "SELL" and cisd_state == "BEARISH"):
            score = min(100, score + 5)
            factors.append("CISD State Confirmed")

        # Assign Grade
        if score >= 85:
            grade = "A+"
        elif score >= 75:
            grade = "A"
        elif score >= 60:
            grade = "B"
        else:
            grade = "C"

        return score, grade, factors

    def _check_rejection(self, c: Candle, zone_top: float, zone_bot: float, is_bullish: bool) -> bool:
        """
        Validates whether the candle confirmed a proper rejection from the zone:
        1. Does not breach 50% Mean Threshold / Consequent Encroachment with candle body.
        2. Leaves a rejection wick in the direction of trade, or prints a strong directional close.
        """
        if not self.trad_require_rejection:
            return True

        bar_range = c.high - c.low
        if bar_range <= 0:
            return False

        zone_mid = (zone_top + zone_bot) / 2.0

        if is_bullish:
            # Respect Mean Threshold: candle body close should be at or above midpoint
            if self.trad_respect_mean_threshold and c.close < zone_mid:
                return False
            # Check for lower rejection wick or strong green close
            lower_wick = min(c.open, c.close) - c.low
            wick_pct = (lower_wick / bar_range) * 100.0
            if wick_pct >= self.trad_min_wick_pct:
                return True
            if c.close > c.open and c.close >= zone_mid:
                return True
            return False
        else:
            # Bearish: close should be at or below midpoint
            if self.trad_respect_mean_threshold and c.close > zone_mid:
                return False
            # Check for upper rejection wick or strong red close
            upper_wick = c.high - max(c.open, c.close)
            wick_pct = (upper_wick / bar_range) * 100.0
            if wick_pct >= self.trad_min_wick_pct:
                return True
            if c.close < c.open and c.close <= zone_mid:
                return True
            return False

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
        if zone_type == "Unicorn" or (zone_type == "Breaker" and (is_htf or is_eq)):
            return "Unicorn Model"
        elif zone_type == "IFVG":
            return "Inverse FVG Model"
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
            return "Hold full size to TP - highest conviction (Breaker + IFVG confluence)."
        elif model == "Inverse FVG Model":
            return "Exit at TP; invalidate early if price closes back through the IFVG boundary."
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

        # Multi-Timeframe Auto-Aggregation if not explicitly passed
        if (htf_candles is None or len(htf_candles) == 0) and self.use_mtf and n >= 6:
            try:
                from ..data.candle_builder import aggregate_candles
                htf_candles = aggregate_candles(candles, target_minutes=self.mtf_narrative_tf)
            except Exception:
                htf_candles = None

        # HTF Bias EMA evaluation
        htf_bias = "NEUTRAL"
        htf_closes = []
        htf_emas = []
        if htf_candles and len(htf_candles) >= 5:
            ema_len = min(self.htf_ema_len, len(htf_candles))
            htf_closes = [c.close for c in htf_candles]
            htf_emas = compute_ema(htf_closes, ema_len)
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

        weekly_highs: Dict[str, float] = {}
        weekly_lows: Dict[str, float] = {}
        for c in candles:
            dt = datetime.fromtimestamp(c.timestamp, tz=IST)
            week_key = dt.strftime("%Y-%W")
            weekly_highs[week_key] = max(weekly_highs.get(week_key, c.high), c.high)
            weekly_lows[week_key] = min(weekly_lows.get(week_key, c.low), c.low)

        sorted_weeks = sorted(weekly_highs.keys())
        pwh = weekly_highs[sorted_weeks[-2]] if len(sorted_weeks) >= 2 else None
        pwl = weekly_lows[sorted_weeks[-2]] if len(sorted_weeks) >= 2 else None

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

        ifvg_bull_list: List[FVG] = []
        ifvg_bear_list: List[FVG] = []

        # Judas Swing state
        current_day_str: Optional[str] = None
        or_high: Optional[float] = None
        or_low: Optional[float] = None
        or_recorded: bool = False
        or_bar_count: int = 0
        judas_bull_armed: bool = False
        judas_bear_armed: bool = False
        judas_fakeout_high: Optional[float] = None
        judas_fakeout_low: Optional[float] = None
        judas_fired_today: bool = False

        # Turtle soup state
        ts_fired_levels: set = set()

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
        judas_swing_events: List[Dict[str, Any]] = []
        turtle_soup_events: List[Dict[str, Any]] = []

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

            day_str = dt.strftime("%Y-%m-%d")
            if day_str != current_day_str:
                current_day_str = day_str
                or_high = None
                or_low = None
                or_recorded = False
                or_bar_count = 0
                judas_bull_armed = False
                judas_bear_armed = False
                judas_fakeout_high = None
                judas_fakeout_low = None
                judas_fired_today = False
                ts_fired_levels.clear()

            # Record Opening Range (typically the 09:15-09:20 opening candle(s))
            if not or_recorded:
                if (dt.hour == 9 and dt.minute >= 15) or dt.hour > 9:
                    if or_high is None:
                        or_high = c.high
                        or_low = c.low
                    else:
                        or_high = max(or_high, c.high)
                        or_low = min(or_low, c.low)
                    or_bar_count += 1
                    if or_bar_count >= self.judas_opening_bars:
                        or_recorded = True

            in_kz1 = is_in_session(dt, self.killzone1)
            in_kz2 = is_in_session(dt, self.killzone2)

            # Skip the literal 09:15 opening candle if configured
            is_open_bar = (dt.hour == 9 and dt.minute == 15)
            if self.skip_open_bar and is_open_bar:
                in_kz1 = False
                in_kz2 = False

            # Killzone gate:
            #   strict_killzone=True  → signals ONLY fire inside KZ1 or KZ2
            #   strict_killzone=False → signals fire anywhere (OOK allowed)
            #   use_killzone=False    → killzone gate fully disabled
            if not self.use_killzone:
                in_killzone = True
            elif self.strict_killzone:
                in_killzone = in_kz1 or in_kz2
            else:
                in_killzone = True   # OOK signals allowed (legacy behaviour)

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

            # FVG Mitigation + CE early failure + Polarity Inversion into IFVG
            for f in fvg_bull_list:
                ce = (f.top + f.bottom) / 2.0
                if not f.mitigated and c.close < f.bottom:
                    f.mitigated = True
                    f.mitigated_bar = bar_idx
                    # Decisive body close below Bullish FVG -> Invert to Bearish IFVG
                    if self.use_ifvg and not f.excluded_fake:
                        ifvg_bear_list.append(FVG(
                            top=f.top,
                            bottom=f.bottom,
                            bar_index=f.bar_index,
                            is_bullish=False,
                            tier=f.tier,
                            c3_consolidating=f.c3_consolidating,
                            has_confluence=f.has_confluence,
                            c1_high=f.c1_high,
                            c1_low=f.c1_low,
                            c3_high=f.c3_high,
                            c3_low=f.c3_low,
                            is_inverse=True,
                            inverted_bar=bar_idx,
                            original_bullish=True
                        ))
                        if len(ifvg_bear_list) > self.max_zones:
                            ifvg_bear_list.pop(0)
                elif self.use_fvg_quality and not f.excluded_fake and (bar_idx - f.bar_index) <= self.fvg_fail_watch_bars and c.close < ce:
                    f.excluded_fake = True

            for f in fvg_bear_list:
                ce = (f.top + f.bottom) / 2.0
                if not f.mitigated and c.close > f.top:
                    f.mitigated = True
                    f.mitigated_bar = bar_idx
                    # Decisive body close above Bearish FVG -> Invert to Bullish IFVG
                    if self.use_ifvg and not f.excluded_fake:
                        ifvg_bull_list.append(FVG(
                            top=f.top,
                            bottom=f.bottom,
                            bar_index=f.bar_index,
                            is_bullish=True,
                            tier=f.tier,
                            c3_consolidating=f.c3_consolidating,
                            has_confluence=f.has_confluence,
                            c1_high=f.c1_high,
                            c1_low=f.c1_low,
                            c3_high=f.c3_high,
                            c3_low=f.c3_low,
                            is_inverse=True,
                            inverted_bar=bar_idx,
                            original_bullish=False
                        ))
                        if len(ifvg_bull_list) > self.max_zones:
                            ifvg_bull_list.pop(0)
                elif self.use_fvg_quality and not f.excluded_fake and (bar_idx - f.bar_index) <= self.fvg_fail_watch_bars and c.close > ce:
                    f.excluded_fake = True

            # Invalidate active IFVGs if price closes completely back through them
            for ifvg in ifvg_bull_list:
                if not ifvg.mitigated and c.close < ifvg.bottom:
                    ifvg.mitigated = True
                    ifvg.mitigated_bar = bar_idx

            for ifvg in ifvg_bear_list:
                if not ifvg.mitigated and c.close > ifvg.top:
                    ifvg.mitigated = True
                    ifvg.mitigated_bar = bar_idx

            # ----------------------------------------------------
            # 3. ORDER BLOCKS (OB) & BREAKERS
            # ----------------------------------------------------
            # Bullish BOS: close > last_sh
            if last_sh is not None and c.close > last_sh and not bos_up_done:
                bos_up_done = True
                last_bos_up_bar = bar_idx
                # Check if this BOS originated from a recent liquidity sweep
                sweep_occurred = (bull_sweep_bar is not None and (bar_idx - bull_sweep_bar) <= self.trad_max_setup_bars)
                ref_bar = bull_sweep_bar if sweep_occurred else (bar_idx - self.ob_search_bars)
                fvg_formed = any(f.bar_index >= ref_bar for f in fvg_bull_list)

                # Search back for last red candle
                for back_i in range(1, min(self.ob_search_bars + 1, bar_idx)):
                    cand = candles[bar_idx - back_i]
                    if cand.close < cand.open:
                        ob_bull_list.append(OrderBlock(
                            top=cand.high,
                            bottom=cand.low,
                            bar_index=bar_idx - back_i,
                            is_bullish=True,
                            has_sweep=sweep_occurred,
                            has_fvg=fvg_formed,
                            sweep_price=bull_sweep_level if sweep_occurred else None,
                            sweep_bar=bull_sweep_bar if sweep_occurred else None,
                            displacement_bar=bar_idx
                        ))
                        if len(ob_bull_list) > self.max_zones:
                            ob_bull_list.pop(0)
                        break

            # Bearish BOS: close < last_sl
            if last_sl is not None and c.close < last_sl and not bos_down_done:
                bos_down_done = True
                last_bos_down_bar = bar_idx
                sweep_occurred_b = (bear_sweep_bar is not None and (bar_idx - bear_sweep_bar) <= self.trad_max_setup_bars)
                ref_bar_b = bear_sweep_bar if sweep_occurred_b else (bar_idx - self.ob_search_bars)
                fvg_formed_b = any(f.bar_index >= ref_bar_b for f in fvg_bear_list)

                # Search back for last green candle
                for back_i in range(1, min(self.ob_search_bars + 1, bar_idx)):
                    cand = candles[bar_idx - back_i]
                    if cand.close > cand.open:
                        ob_bear_list.append(OrderBlock(
                            top=cand.high,
                            bottom=cand.low,
                            bar_index=bar_idx - back_i,
                            is_bullish=False,
                            has_sweep=sweep_occurred_b,
                            has_fvg=fvg_formed_b,
                            sweep_price=bear_sweep_level if sweep_occurred_b else None,
                            sweep_bar=bear_sweep_bar if sweep_occurred_b else None,
                            displacement_bar=bar_idx
                        ))
                        if len(ob_bear_list) > self.max_zones:
                            ob_bear_list.pop(0)
                        break

            # Mitigation and Breaker Block conversion
            for ob in ob_bull_list:
                if not ob.mitigated and c.close < ob.bottom:
                    ob.mitigated = True
                    ob.mitigated_bar = bar_idx
                    if self.show_ob:
                        ob_bear_list.append(OrderBlock(
                            top=ob.top,
                            bottom=ob.bottom,
                            bar_index=bar_idx,
                            is_bullish=False,
                            is_breaker=True,
                            has_sweep=ob.has_sweep,
                            has_fvg=ob.has_fvg,
                            sweep_price=ob.sweep_price,
                            sweep_bar=ob.sweep_bar
                        ))
                        if len(ob_bear_list) > self.max_zones:
                            ob_bear_list.pop(0)

            for ob in ob_bear_list:
                if not ob.mitigated and c.close > ob.top:
                    ob.mitigated = True
                    ob.mitigated_bar = bar_idx
                    if self.show_ob:
                        ob_bull_list.append(OrderBlock(
                            top=ob.top,
                            bottom=ob.bottom,
                            bar_index=bar_idx,
                            is_bullish=True,
                            is_breaker=True,
                            has_sweep=ob.has_sweep,
                            has_fvg=ob.has_fvg,
                            sweep_price=ob.sweep_price,
                            sweep_bar=ob.sweep_bar
                        ))
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

            # Expire stale sweeps & invalidate on adverse close
            max_sweep_bars = self.trad_max_setup_bars if self.traditional_ict else self.sweep_valid_bars
            if bull_sweep_active and bull_sweep_bar is not None and (bar_idx - bull_sweep_bar > max_sweep_bars):
                bull_sweep_active = False
            if bear_sweep_active and bear_sweep_bar is not None and (bar_idx - bear_sweep_bar > max_sweep_bars):
                bear_sweep_active = False

            if self.traditional_ict:
                if bull_sweep_active and bull_sweep_level is not None and c.close < bull_sweep_level:
                    bull_sweep_active = False
                if bear_sweep_active and bear_sweep_level is not None and c.close > bear_sweep_level:
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

            # Dynamic Multi-Timeframe (MTF) Bias evaluation
            current_htf_bias = htf_bias
            if htf_candles and htf_emas:
                target_sec = self.mtf_narrative_tf * 60
                last_closed_htf_idx = None
                for h_idx in range(len(htf_candles) - 1, -1, -1):
                    if c.timestamp >= (htf_candles[h_idx].timestamp + target_sec):
                        last_closed_htf_idx = h_idx
                        break
                if last_closed_htf_idx is not None and last_closed_htf_idx < len(htf_emas):
                    if htf_closes[last_closed_htf_idx] > htf_emas[last_closed_htf_idx]:
                        current_htf_bias = "BULLISH"
                    elif htf_closes[last_closed_htf_idx] < htf_emas[last_closed_htf_idx]:
                        current_htf_bias = "BEARISH"

            if self.use_mtf and self.mtf_block_counter:
                is_htf_ok_buy = current_htf_bias in ("BULLISH", "NEUTRAL")
                is_htf_ok_sell = current_htf_bias in ("BEARISH", "NEUTRAL")
            else:
                is_htf_ok_buy = not self.use_htf_bias or (current_htf_bias == "BULLISH" or (not self.htf_bias_strict and current_htf_bias == "NEUTRAL"))
                is_htf_ok_sell = not self.use_htf_bias or (current_htf_bias == "BEARISH" or (not self.htf_bias_strict and current_htf_bias == "NEUTRAL"))

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
                        if self.traditional_ict:
                            # FVG must originate in current sweep setup window
                            if bull_sweep_bar is not None and fvg.bar_index < bull_sweep_bar:
                                continue
                            if self._fvg_tier_rank(fvg.tier) < 2:
                                continue
                        if c.low <= fvg.top and c.high >= fvg.bottom:
                            if not self.traditional_ict or self._check_rejection(c, fvg.top, fvg.bottom, is_bullish=True):
                                zone_top = fvg.top
                                zone_bot = fvg.bottom
                                zone_type = "FVG"
                                break
                # Check Bullish OBs if no FVG touched or confirmed
                if zone_top is None:
                    for ob in reversed(ob_bull_list):
                        if not ob.mitigated and c.low <= ob.top and c.high >= ob.bottom:
                            if self.traditional_ict and not ob.is_breaker:
                                ob_has_fvg = ob.has_fvg or any(f.bar_index >= ob.bar_index for f in fvg_bull_list)
                                if self.trad_require_sweep and not ob.has_sweep:
                                    continue
                                if self.trad_require_fvg and not ob_has_fvg:
                                    continue
                                if bull_sweep_bar is not None and ob.bar_index < (bull_sweep_bar - 2):
                                    continue
                            if not self.traditional_ict or self._check_rejection(c, ob.top, ob.bottom, is_bullish=True):
                                zone_top = ob.top
                                zone_bot = ob.bottom
                                zone_type = "Breaker" if ob.is_breaker else "OB"
                                break

                # Check Bullish IFVGs (Inverse FVGs) if no regular FVG or OB touched or confirmed
                if zone_top is None and self.use_ifvg:
                    for ifvg in reversed(ifvg_bull_list):
                        if not ifvg.mitigated:
                            if self.traditional_ict:
                                if bull_sweep_bar is not None and ifvg.inverted_bar is not None and ifvg.inverted_bar < (bull_sweep_bar - 5):
                                    continue
                                if self._fvg_tier_rank(ifvg.tier) < 2:
                                    continue
                            if c.low <= ifvg.top and c.high >= ifvg.bottom:
                                if not self.traditional_ict or self._check_rejection(c, ifvg.top, ifvg.bottom, is_bullish=True):
                                    zone_top = ifvg.top
                                    zone_bot = ifvg.bottom
                                    # Unicorn model check: Breaker Block + IFVG confluence
                                    has_breaker_conf = any(
                                        ob.is_breaker and not (ob.top < ifvg.bottom or ob.bottom > ifvg.top)
                                        for ob in ob_bull_list if not ob.mitigated
                                    )
                                    zone_type = "Unicorn" if has_breaker_conf else "IFVG"
                                    break

                if zone_top is not None:
                    entry_price = c.close
                    sl_price = float(round(min(zone_bot, bull_sweep_level or zone_bot) - atr_val * self.atr_buffer_mult, 2))
                    tp_price = float(round(entry_price + (entry_price - sl_price) * self.risk_reward, 2))
                    if self.mtf_target_htf:
                        htf_target = pdh or pwh
                        if htf_target is not None and htf_target > entry_price and htf_target > tp_price:
                            tp_price = float(round(htf_target, 2))
                    last_entry_model = self._entry_model_name(bull_sweep_tier, zone_type, in_kz1)

                    # Confluence Scoring & Rejection metrics
                    body = abs(c.close - c.open)
                    total_range = c.high - c.low
                    lower_wick = min(c.open, c.close) - c.low
                    wick_pct = (lower_wick / total_range * 100.0) if total_range > 0 else 0.0
                    mt_level = (zone_top + zone_bot) / 2.0
                    mt_defended = c.close >= mt_level

                    score, grade, factors = self._score_signal(
                        signal_dir="BUY",
                        model=last_entry_model,
                        tier=bull_sweep_tier,
                        in_killzone=in_killzone,
                        htf_bias=htf_bias,
                        cisd_state=cisd_state,
                        wick_pct=wick_pct,
                        mt_defended=mt_defended,
                        is_breaker=(zone_type == "Breaker" or zone_type == "Unicorn"),
                        is_ifvg=(zone_type == "IFVG" or zone_type == "Unicorn")
                    )

                    allow_signal = not self.enable_confluence_filter or score >= self.min_confluence_score

                    if allow_signal:
                        buy_signal = True
                        bull_signal_fired = True
                        bull_sweep_active = False
                        current_signal = "BUY"
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
                            "cisd": cisd_state,
                            "confluence_score": score,
                            "grade": grade,
                            "confluence_factors": factors
                        })

            # SELL evaluation
            if eval_bar and in_killzone and is_premium_ok and (not self.use_cisd or cisd_state == "BEARISH") and is_htf_ok_sell and bear_sweep_active and not bear_signal_fired:
                zone_top_b = None
                zone_bot_b = None
                zone_type_b = ""
                # Check Bearish FVGs
                for fvg in reversed(fvg_bear_list):
                    if not fvg.mitigated and (not self.use_fvg_quality or (not fvg.excluded_fake and self._fvg_tier_rank(fvg.tier) >= self._min_tier_rank())):
                        if self.traditional_ict:
                            if bear_sweep_bar is not None and fvg.bar_index < bear_sweep_bar:
                                continue
                            if self._fvg_tier_rank(fvg.tier) < 2:
                                continue
                        if c.low <= fvg.top and c.high >= fvg.bottom:
                            if not self.traditional_ict or self._check_rejection(c, fvg.top, fvg.bottom, is_bullish=False):
                                zone_top_b = fvg.top
                                zone_bot_b = fvg.bottom
                                zone_type_b = "FVG"
                                break
                # Check Bearish OBs
                if zone_top_b is None:
                    for ob in reversed(ob_bear_list):
                        if not ob.mitigated and c.low <= ob.top and c.high >= ob.bottom:
                            if self.traditional_ict and not ob.is_breaker:
                                ob_has_fvg = ob.has_fvg or any(f.bar_index >= ob.bar_index for f in fvg_bear_list)
                                if self.trad_require_sweep and not ob.has_sweep:
                                    continue
                                if self.trad_require_fvg and not ob_has_fvg:
                                    continue
                                if bear_sweep_bar is not None and ob.bar_index < (bear_sweep_bar - 2):
                                    continue
                            if not self.traditional_ict or self._check_rejection(c, ob.top, ob.bottom, is_bullish=False):
                                zone_top_b = ob.top
                                zone_bot_b = ob.bottom
                                zone_type_b = "Breaker" if ob.is_breaker else "OB"
                                break

                # Check Bearish IFVGs (Inverse FVGs) if no regular FVG or OB touched or confirmed
                if zone_top_b is None and self.use_ifvg:
                    for ifvg in reversed(ifvg_bear_list):
                        if not ifvg.mitigated:
                            if self.traditional_ict:
                                if bear_sweep_bar is not None and ifvg.inverted_bar is not None and ifvg.inverted_bar < (bear_sweep_bar - 5):
                                    continue
                                if self._fvg_tier_rank(ifvg.tier) < 2:
                                    continue
                            if c.low <= ifvg.top and c.high >= ifvg.bottom:
                                if not self.traditional_ict or self._check_rejection(c, ifvg.top, ifvg.bottom, is_bullish=False):
                                    zone_top_b = ifvg.top
                                    zone_bot_b = ifvg.bottom
                                    # Unicorn model check: Breaker Block + IFVG confluence
                                    has_breaker_conf_b = any(
                                        ob.is_breaker and not (ob.top < ifvg.bottom or ob.bottom > ifvg.top)
                                        for ob in ob_bear_list if not ob.mitigated
                                    )
                                    zone_type_b = "Unicorn" if has_breaker_conf_b else "IFVG"
                                    break

                if zone_top_b is not None:
                    entry_price = c.close
                    sl_price = float(round(max(zone_top_b, bear_sweep_level or zone_top_b) + atr_val * self.atr_buffer_mult, 2))
                    tp_price = float(round(entry_price - (sl_price - entry_price) * self.risk_reward, 2))
                    if self.mtf_target_htf:
                        htf_target = pdl or pwl
                        if htf_target is not None and htf_target < entry_price and htf_target < tp_price:
                            tp_price = float(round(htf_target, 2))
                    last_entry_model = self._entry_model_name(bear_sweep_tier, zone_type_b, in_kz1)

                    # Confluence Scoring & Rejection metrics
                    body = abs(c.close - c.open)
                    total_range = c.high - c.low
                    upper_wick = c.high - max(c.open, c.close)
                    wick_pct = (upper_wick / total_range * 100.0) if total_range > 0 else 0.0
                    mt_level_b = (zone_top_b + zone_bot_b) / 2.0
                    mt_defended = c.close <= mt_level_b

                    score, grade, factors = self._score_signal(
                        signal_dir="SELL",
                        model=last_entry_model,
                        tier=bear_sweep_tier,
                        in_killzone=in_killzone,
                        htf_bias=htf_bias,
                        cisd_state=cisd_state,
                        wick_pct=wick_pct,
                        mt_defended=mt_defended,
                        is_breaker=(zone_type_b == "Breaker" or zone_type_b == "Unicorn"),
                        is_ifvg=(zone_type_b == "IFVG" or zone_type_b == "Unicorn")
                    )

                    allow_signal = not self.enable_confluence_filter or score >= self.min_confluence_score

                    if allow_signal:
                        sell_signal = True
                        bear_signal_fired = True
                        bear_sweep_active = False
                        current_signal = "SELL"
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
                            "cisd": cisd_state,
                            "confluence_score": score,
                            "grade": grade,
                            "confluence_factors": factors
                        })

            # ----------------------------------------------------
            # 5b. JUDAS SWING MODEL (Opening Range Manipulation & Trap)
            # ----------------------------------------------------
            if self.use_judas_swing and eval_bar and or_recorded and not judas_fired_today:
                in_judas_win = is_in_session(dt, self.judas_window)
                if in_judas_win:
                    # Arm fakeout traps when price breaches OR extremes
                    if or_high is not None and c.high > or_high:
                        judas_bear_armed = True
                        judas_fakeout_high = max(judas_fakeout_high or or_high, c.high)

                    if or_low is not None and c.low < or_low:
                        judas_bull_armed = True
                        judas_fakeout_low = min(judas_fakeout_low or or_low, c.low)

                    # Bearish Judas Reversal: Breached OR High, then closed back below OR High
                    if judas_bear_armed and or_high is not None and c.close < or_high and not sell_signal:
                        body = abs(c.close - c.open)
                        total_range = c.high - c.low
                        upper_wick = c.high - max(c.open, c.close)
                        wick_pct = (upper_wick / total_range * 100.0) if total_range > 0 else 0.0

                        js_score, js_grade, js_factors = self._score_signal(
                            signal_dir="SELL",
                            model="Judas Swing Model",
                            tier="Opening Range High Trap",
                            in_killzone=True,
                            htf_bias=htf_bias,
                            cisd_state=cisd_state,
                            wick_pct=wick_pct,
                            mt_defended=True
                        )

                        if not self.enable_confluence_filter or js_score >= self.min_confluence_score:
                            entry_price = c.close
                            sl_price = float(round((judas_fakeout_high or c.high) + atr_val * self.atr_buffer_mult, 2))
                            tp_price = float(round(entry_price - (sl_price - entry_price) * self.risk_reward, 2))
                            sell_signal = True
                            judas_fired_today = True
                            judas_bear_armed = False
                            current_signal = "SELL"
                            last_entry_model = "Judas Swing Model"
                            bias_state = "BEARISH"

                            judas_swing_events.append({
                                "type": "JUDAS_SWING_SELL",
                                "bar_index": bar_idx,
                                "time": c.timestamp,
                                "entry_price": entry_price,
                                "sl": sl_price,
                                "tp": tp_price,
                                "score": js_score,
                                "grade": js_grade
                            })

                            signals.append({
                                "signal": "SELL",
                                "bar_index": bar_idx,
                                "time": c.timestamp,
                                "entry_price": entry_price,
                                "sl_price": sl_price,
                                "tp_price": tp_price,
                                "tier": "Opening Range High Trap",
                                "model": "Judas Swing Model",
                                "exit_plan": "Exit at Opening Range Low / Target Liquidity",
                                "cisd": cisd_state,
                                "confluence_score": js_score,
                                "grade": js_grade,
                                "confluence_factors": js_factors
                            })

                    # Bullish Judas Reversal: Breached OR Low, then closed back above OR Low
                    elif judas_bull_armed and or_low is not None and c.close > or_low and not buy_signal:
                        body = abs(c.close - c.open)
                        total_range = c.high - c.low
                        lower_wick = min(c.open, c.close) - c.low
                        wick_pct = (lower_wick / total_range * 100.0) if total_range > 0 else 0.0

                        js_score, js_grade, js_factors = self._score_signal(
                            signal_dir="BUY",
                            model="Judas Swing Model",
                            tier="Opening Range Low Trap",
                            in_killzone=True,
                            htf_bias=htf_bias,
                            cisd_state=cisd_state,
                            wick_pct=wick_pct,
                            mt_defended=True
                        )

                        if not self.enable_confluence_filter or js_score >= self.min_confluence_score:
                            entry_price = c.close
                            sl_price = float(round((judas_fakeout_low or c.low) - atr_val * self.atr_buffer_mult, 2))
                            tp_price = float(round(entry_price + (entry_price - sl_price) * self.risk_reward, 2))
                            buy_signal = True
                            judas_fired_today = True
                            judas_bull_armed = False
                            current_signal = "BUY"
                            last_entry_model = "Judas Swing Model"
                            bias_state = "BULLISH"

                            judas_swing_events.append({
                                "type": "JUDAS_SWING_BUY",
                                "bar_index": bar_idx,
                                "time": c.timestamp,
                                "entry_price": entry_price,
                                "sl": sl_price,
                                "tp": tp_price,
                                "score": js_score,
                                "grade": js_grade
                            })

                            signals.append({
                                "signal": "BUY",
                                "bar_index": bar_idx,
                                "time": c.timestamp,
                                "entry_price": entry_price,
                                "sl_price": sl_price,
                                "tp_price": tp_price,
                                "tier": "Opening Range Low Trap",
                                "model": "Judas Swing Model",
                                "exit_plan": "Exit at Opening Range High / Target Liquidity",
                                "cisd": cisd_state,
                                "confluence_score": js_score,
                                "grade": js_grade,
                                "confluence_factors": js_factors
                            })

            # ----------------------------------------------------
            # 5c. TURTLE SOUP MODEL (HTF Liquidity False Breakout)
            # ----------------------------------------------------
            if self.use_turtle_soup and eval_bar and (not self.use_killzone or in_killzone):
                # Bearish Turtle Soup (Sweep PDH / PWH)
                ts_bear_targets = [("PDH", pdh), ("PWH", pwh)]
                for lvl_name, lvl_val in ts_bear_targets:
                    if lvl_val is not None and lvl_name in self.ts_targets and lvl_name not in ts_fired_levels:
                        if c.high > lvl_val:
                            closed_inside = (not self.ts_require_close_inside) or (c.close < lvl_val)
                            total_range = c.high - c.low
                            upper_wick = c.high - max(c.open, c.close)
                            wick_pct = (upper_wick / total_range * 100.0) if total_range > 0 else 0.0

                            if closed_inside and wick_pct >= self.ts_min_wick_pct and not sell_signal:
                                ts_score, ts_grade, ts_factors = self._score_signal(
                                    signal_dir="SELL",
                                    model="Turtle Soup Model",
                                    tier=lvl_name,
                                    in_killzone=in_killzone,
                                    htf_bias=htf_bias,
                                    cisd_state=cisd_state,
                                    wick_pct=wick_pct,
                                    mt_defended=True
                                )

                                if not self.enable_confluence_filter or ts_score >= self.min_confluence_score:
                                    entry_price = c.close
                                    sl_price = float(round(c.high + atr_val * self.atr_buffer_mult, 2))
                                    tp_price = float(round(entry_price - (sl_price - entry_price) * self.risk_reward, 2))
                                    sell_signal = True
                                    current_signal = "SELL"
                                    last_entry_model = f"Turtle Soup Model ({lvl_name})"
                                    bias_state = "BEARISH"
                                    ts_fired_levels.add(lvl_name)

                                    turtle_soup_events.append({
                                        "type": f"TURTLE_SOUP_SELL_{lvl_name}",
                                        "bar_index": bar_idx,
                                        "time": c.timestamp,
                                        "level": lvl_val,
                                        "entry_price": entry_price,
                                        "sl": sl_price,
                                        "tp": tp_price,
                                        "score": ts_score,
                                        "grade": ts_grade
                                    })

                                    signals.append({
                                        "signal": "SELL",
                                        "bar_index": bar_idx,
                                        "time": c.timestamp,
                                        "entry_price": entry_price,
                                        "sl_price": sl_price,
                                        "tp_price": tp_price,
                                        "tier": lvl_name,
                                        "model": f"Turtle Soup Model ({lvl_name})",
                                        "exit_plan": f"Turtle Soup: target opposite equilibrium / {lvl_name} rejection",
                                        "cisd": cisd_state,
                                        "confluence_score": ts_score,
                                        "grade": ts_grade,
                                        "confluence_factors": ts_factors
                                    })
                                    break

                # Bullish Turtle Soup (Sweep PDL / PWL)
                ts_bull_targets = [("PDL", pdl), ("PWL", pwl)]
                for lvl_name, lvl_val in ts_bull_targets:
                    if lvl_val is not None and lvl_name in self.ts_targets and lvl_name not in ts_fired_levels:
                        if c.low < lvl_val:
                            closed_inside = (not self.ts_require_close_inside) or (c.close > lvl_val)
                            total_range = c.high - c.low
                            lower_wick = min(c.open, c.close) - c.low
                            wick_pct = (lower_wick / total_range * 100.0) if total_range > 0 else 0.0

                            if closed_inside and wick_pct >= self.ts_min_wick_pct and not buy_signal:
                                ts_score, ts_grade, ts_factors = self._score_signal(
                                    signal_dir="BUY",
                                    model="Turtle Soup Model",
                                    tier=lvl_name,
                                    in_killzone=in_killzone,
                                    htf_bias=htf_bias,
                                    cisd_state=cisd_state,
                                    wick_pct=wick_pct,
                                    mt_defended=True
                                )

                                if not self.enable_confluence_filter or ts_score >= self.min_confluence_score:
                                    entry_price = c.close
                                    sl_price = float(round(c.low - atr_val * self.atr_buffer_mult, 2))
                                    tp_price = float(round(entry_price + (entry_price - sl_price) * self.risk_reward, 2))
                                    buy_signal = True
                                    current_signal = "BUY"
                                    last_entry_model = f"Turtle Soup Model ({lvl_name})"
                                    bias_state = "BULLISH"
                                    ts_fired_levels.add(lvl_name)

                                    turtle_soup_events.append({
                                        "type": f"TURTLE_SOUP_BUY_{lvl_name}",
                                        "bar_index": bar_idx,
                                        "time": c.timestamp,
                                        "level": lvl_val,
                                        "entry_price": entry_price,
                                        "sl": sl_price,
                                        "tp": tp_price,
                                        "score": ts_score,
                                        "grade": ts_grade
                                    })

                                    signals.append({
                                        "signal": "BUY",
                                        "bar_index": bar_idx,
                                        "time": c.timestamp,
                                        "entry_price": entry_price,
                                        "sl_price": sl_price,
                                        "tp_price": tp_price,
                                        "tier": lvl_name,
                                        "model": f"Turtle Soup Model ({lvl_name})",
                                        "exit_plan": f"Turtle Soup: target opposite equilibrium / {lvl_name} rejection",
                                        "cisd": cisd_state,
                                        "confluence_score": ts_score,
                                        "grade": ts_grade,
                                        "confluence_factors": ts_factors
                                    })
                                    break

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
        all_fvgs = fvg_bull_list + fvg_bear_list + ifvg_bull_list + ifvg_bear_list
        fvg_payload = [
            {
                "top": f.top,
                "bottom": f.bottom,
                "start_bar": max(0, (f.inverted_bar if f.is_inverse and f.inverted_bar is not None else f.bar_index) - 2),
                "end_bar": min(n - 1, (f.inverted_bar if f.is_inverse and f.inverted_bar is not None else f.bar_index) + 20),
                "bar_index": f.bar_index,
                "time": candles[f.bar_index].timestamp if f.bar_index < n else 0,
                "is_bullish": f.is_bullish,
                "is_inverse": f.is_inverse,
                "tier": f.tier,
                "mitigated": f.mitigated,
                "excluded_fake": f.excluded_fake,
                "c1_high": f.c1_high,
                "c1_low": f.c1_low,
                "c3_high": f.c3_high,
                "c3_low": f.c3_low
            }
            for f in all_fvgs
        ]

        ifvg_payload = [f for f in fvg_payload if f.get("is_inverse")]

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
            "judas_swing_events": judas_swing_events,
            "turtle_soup_events": turtle_soup_events,
            "fvg_zones": fvg_payload,
            "ifvg_zones": ifvg_payload,
            "order_blocks": ob_payload,
            "liquidity_levels": liquidity_payload,
            "pdh": pdh,
            "pdl": pdl,
            "pwh": pwh,
            "pwl": pwl,
            "active_trade": {
                "entry_price": entry_price,
                "sl_price": sl_price,
                "tp_price": tp_price,
                "signal": current_signal,
                "bias": bias_state
            } if bias_state != "NEUTRAL" else None
        }
