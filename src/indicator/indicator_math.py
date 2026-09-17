"""Mathematical and indicator helper routines."""
import numpy as np
import pandas as pd
from typing import List, Tuple, Optional
from .models import Candle

def compute_atr(candles: List[Candle], period: int = 14) -> List[float]:
    """Calculates Wilder's Average True Range."""
    if len(candles) < 2:
        return [0.0] * len(candles)
    
    highs = np.array([c.high for c in candles])
    lows = np.array([c.low for c in candles])
    closes = np.array([c.close for c in candles])
    
    tr = np.zeros(len(candles))
    tr[0] = highs[0] - lows[0]
    for i in range(1, len(candles)):
        hl = highs[i] - lows[i]
        hpc = abs(highs[i] - closes[i - 1])
        lpc = abs(lows[i] - closes[i - 1])
        tr[i] = max(hl, hpc, lpc)
    
    atr = np.zeros(len(candles))
    if len(candles) <= period:
        atr[-1] = np.mean(tr)
        return list(atr)
    
    atr[period - 1] = np.mean(tr[:period])
    for i in range(period, len(candles)):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    
    return list(atr)

def compute_ema(prices: List[float], period: int = 50) -> List[float]:
    """Exponential Moving Average."""
    if not prices:
        return []
    s = pd.Series(prices)
    ema = s.ewm(span=period, adjust=False).mean()
    return list(ema)
