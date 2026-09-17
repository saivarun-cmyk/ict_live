"""
Candle Aggregator: Converts 1-minute candles into 5-minute, 15-minute, or 30-minute OHLCV bars.
"""

from typing import List
from ..indicator.models import Candle

def aggregate_candles(candles_1m: List[Candle], target_minutes: int = 5) -> List[Candle]:
    if not candles_1m or target_minutes <= 1:
        return candles_1m

    target_seconds = target_minutes * 60
    aggregated: List[Candle] = []

    current_bucket_start = None
    cur_open = 0.0
    cur_high = -float('inf')
    cur_low = float('inf')
    cur_close = 0.0
    cur_vol = 0.0

    for c in candles_1m:
        bucket = (c.timestamp // target_seconds) * target_seconds
        if current_bucket_start is None:
            current_bucket_start = bucket
            cur_open = c.open
            cur_high = c.high
            cur_low = c.low
            cur_close = c.close
            cur_vol = c.volume
        elif bucket == current_bucket_start:
            cur_high = max(cur_high, c.high)
            cur_low = min(cur_low, c.low)
            cur_close = c.close
            cur_vol += c.volume
        else:
            aggregated.append(Candle(
                timestamp=current_bucket_start,
                open=cur_open,
                high=cur_high,
                low=cur_low,
                close=cur_close,
                volume=cur_vol
            ))
            current_bucket_start = bucket
            cur_open = c.open
            cur_high = c.high
            cur_low = c.low
            cur_close = c.close
            cur_vol = c.volume

    if current_bucket_start is not None:
        aggregated.append(Candle(
            timestamp=current_bucket_start,
            open=cur_open,
            high=cur_high,
            low=cur_low,
            close=cur_close,
            volume=cur_vol
        ))

    return aggregated
