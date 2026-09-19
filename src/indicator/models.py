"""Data structures and representations for ICT elements."""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

@dataclass
class Candle:
    timestamp: int       # epoch timestamp (seconds or ms)
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

@dataclass
class SwingPoint:
    bar_index: int
    price: float
    is_high: bool
    is_eq: bool = False  # Equal Highs (EQH) or Equal Lows (EQL)

@dataclass
class LiquidityLevel:
    price: float
    bar_index: int
    tier: str            # "Swing", "EQH", "EQL", "PDH", "PDL", "PWH", "PWL", "PMH", "PML"
    is_eq: bool = False
    swept: bool = False
    swept_bar: Optional[int] = None

@dataclass
class FVG:
    top: float
    bottom: float
    bar_index: int       # Candle 3 index
    is_bullish: bool
    tier: str            # "Standard", "Higher Probability", "Highest Probability"
    c3_consolidating: bool
    has_confluence: bool
    mitigated: bool = False
    mitigated_bar: Optional[int] = None
    excluded_fake: bool = False
    c1_high: float = 0.0
    c1_low: float = 0.0
    c3_high: float = 0.0
    c3_low: float = 0.0
    is_inverse: bool = False
    inverted_bar: Optional[int] = None
    original_bullish: bool = True

@dataclass
class OrderBlock:
    top: float
    bottom: float
    bar_index: int
    is_bullish: bool
    is_breaker: bool = False
    mitigated: bool = False
    mitigated_bar: Optional[int] = None
    has_sweep: bool = False
    has_fvg: bool = False
    sweep_price: Optional[float] = None
    sweep_bar: Optional[int] = None
    displacement_bar: Optional[int] = None

@dataclass
class JudasSwingEvent:
    bar_index: int
    time: int
    is_bullish: bool       # True = Fakeout down, true expansion up
    fakeout_extreme: float # High/Low of the trap
    sweep_level: float     # Opening range high/low that was breached
    displacement_fvg: Optional[FVG] = None
    confirmed: bool = False

@dataclass
class TurtleSoupEvent:
    bar_index: int
    time: int
    is_bullish: bool       # True = Swept low and closed back inside (buy reversal)
    target_level: str      # "PDH", "PDL", "PWH", "PWL"
    level_price: float
    sweep_extreme: float
    rejection_wick_pct: float
    confirmed: bool = False

@dataclass
class SignalResult:
    signal: str          # "BUY", "SELL", "HOLD"
    entry_model: str     # "Unicorn Model", "Silver Bullet Model", "Judas Swing Model", etc.
    entry_price: float
    sl_price: float
    tp_price: float
    exit_model_plan: str
    tier: str
    cisd_state: str
    bias_state: str      # "BULLISH", "BEARISH", "NEUTRAL"
    bar_index: int
    time: int
    confluence_score: int = 0
    grade: str = "A"     # "A+", "A", "B"
    confluence_factors: List[str] = field(default_factory=list)

