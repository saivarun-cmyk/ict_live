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

@dataclass
class OrderBlock:
    top: float
    bottom: float
    bar_index: int
    is_bullish: bool
    is_breaker: bool = False
    mitigated: bool = False
    mitigated_bar: Optional[int] = None

@dataclass
class SignalResult:
    signal: str          # "BUY", "SELL", "HOLD"
    entry_model: str     # "Unicorn Model", "Silver Bullet Model", etc.
    entry_price: float
    sl_price: float
    tp_price: float
    exit_model_plan: str
    tier: str
    cisd_state: str
    bias_state: str      # "BULLISH", "BEARISH", "NEUTRAL"
    bar_index: int
    time: int
