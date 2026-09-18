"""
Upstox API v2 Client and Realistic Market Session Data Generator.
Produces authentic trading day sessions (09:15 - 15:30 IST) with ICT swings,
displacement legs, Fair Value Gaps, liquidity sweeps, and Killzone action.
"""

import os
import time
import math
import random
import logging
from datetime import datetime, timedelta, time as dtime
import zoneinfo
from typing import List, Dict, Any, Optional
import requests

from ..indicator.models import Candle

logger = logging.getLogger("UpstoxClient")
IST = zoneinfo.ZoneInfo("Asia/Kolkata")

class UpstoxClient:
    def __init__(self, api_key: str = "", api_secret: str = "", access_token: str = ""):
        self.api_key = api_key or os.getenv("UPSTOX_API_KEY", "")
        self.api_secret = api_secret or os.getenv("UPSTOX_API_SECRET", "")
        self.access_token = access_token or os.getenv("UPSTOX_ACCESS_TOKEN", "")
        self.base_url = "https://api.upstox.com/v2"

    def is_configured(self) -> bool:
        return bool(self.access_token and len(self.access_token) > 10)

    def fetch_historical_candles(
        self,
        instrument_key: str,
        interval: str = "5minute",
        days: int = 7
    ) -> List[Candle]:
        """
        Fetches historical candles from Upstox v2 API, or generates realistic
        IST trading-session candles (09:15 - 15:30) with ICT patterns.
        """
        mock_replay = os.getenv("MOCK_REPLAY", "false").lower() == "true"
        if not mock_replay and self.is_configured():
            headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {self.access_token}"
            }
            to_date = datetime.now(tz=IST).strftime("%Y-%m-%d")
            from_date = (datetime.now(tz=IST) - timedelta(days=days)).strftime("%Y-%m-%d")
            import urllib.parse
            encoded_key = urllib.parse.quote(instrument_key, safe='')
            # Upstox v2 only supports 1minute, 30minute, day, week, month
            req_interval = "1minute" if ("1minute" in interval or "5minute" in interval or "15minute" in interval) else "30minute"
            url = f"{self.base_url}/historical-candle/{encoded_key}/{req_interval}/{to_date}/{from_date}"
            try:
                resp = requests.get(url, headers=headers, timeout=6)
                if resp.status_code == 200:
                    data = resp.json().get("data", {}).get("candles", [])
                    if data and len(data) > 20:
                        raw_candles: List[Candle] = []
                        for row in reversed(data):
                            ts = int(datetime.fromisoformat(row[0].replace("Z", "+00:00")).timestamp())
                            raw_candles.append(Candle(
                                timestamp=ts,
                                open=float(row[1]),
                                high=float(row[2]),
                                low=float(row[3]),
                                close=float(row[4]),
                                volume=float(row[5])
                            ))
                        from .candle_builder import aggregate_candles
                        if "5minute" in interval:
                            return aggregate_candles(raw_candles, target_minutes=5)
                        elif "15minute" in interval:
                            return aggregate_candles(raw_candles, target_minutes=15)
                        return raw_candles
                else:
                    logger.warning(f"Upstox API returned {resp.status_code}: {resp.text[:200]}")
            except Exception as e:
                logger.warning(f"Live fetch exception for {instrument_key}: {e}")

        # Generate realistic IST market session candles
        return self.generate_synthetic_history(instrument_key, interval=interval, days=days)

    def generate_synthetic_history(
        self,
        instrument_key: str,
        interval: str = "5minute",
        days: int = 4
    ) -> List[Candle]:
        """
        Generates genuine Indian market trading sessions:
        - 09:15 - 15:30 IST
        - Skips weekends
        - Creates market open drive (Killzone 1: 09:15-10:30), midday consolidation,
          and afternoon expansion (Killzone 2: 13:30-15:00) with liquidity sweeps and FVGs!
        """
        base_prices = {
            "NSE_INDEX|Nifty 50": 23270.60,
            "NSE_INDEX|Nifty Bank": 56055.75,
            "BSE_INDEX|SENSEX": 74314.59,
            "NSE_EQ|INE002A01018": 2980.0,
            "NSE_EQ|INE040A01034": 1650.0,
            "NSE_EQ|INE467B01029": 4420.0,
            "NSE_EQ|INE009A01021": 1910.0,
            "NSE_EQ|INE090A01021": 1230.0,
        }
        price = base_prices.get(instrument_key, 25000.0)

        step_minutes = 5
        if "1minute" in interval:
            step_minutes = 1
        elif "15minute" in interval:
            step_minutes = 15

        now = datetime.now(tz=IST)
        trading_dates = []
        cur_day = now.date()
        while len(trading_dates) < days:
            if cur_day.weekday() < 5:  # Monday to Friday
                trading_dates.append(cur_day)
            cur_day -= timedelta(days=1)
        trading_dates.reverse()

        candles: List[Candle] = []
        import hashlib
        inst_seed = int(hashlib.md5(instrument_key.encode('utf-8')).hexdigest()[:8], 16)
        random.seed(inst_seed)  # Unique realistic patterns per instrument

        volatility = price * 0.001
        kz1_disp = [(inst_seed % 5) + 5, ((inst_seed >> 3) % 5) + 11]
        kz2_disp = [((inst_seed >> 6) % 6) + 38, ((inst_seed >> 9) % 6) + 47]
        sweep_bars = [(inst_seed % 4) + 3, ((inst_seed >> 4) % 6) + 16, ((inst_seed >> 8) % 6) + 43]

        for day_idx, t_date in enumerate(trading_dates):
            # Market open at 09:15 IST
            session_start = datetime(t_date.year, t_date.month, t_date.day, 9, 15, tzinfo=IST)
            session_end = datetime(t_date.year, t_date.month, t_date.day, 15, 30, tzinfo=IST)

            # Day opening gap
            day_gap = random.choice([-1.0, 1.0]) * volatility * 1.5
            price += day_gap

            cur_time = session_start
            bar_in_day = 0

            # Daily bias for this session
            day_bias = 1.0 if (day_idx % 2 == 0) else -1.0

            while cur_time < session_end:
                t_sec = int(cur_time.timestamp())
                bar_in_day += 1

                # Phased behavior:
                # 09:15 - 10:30: Opening Killzone - high volatility displacement & sweeps
                # 10:30 - 13:30: Midday chop/consolidation
                # 13:30 - 15:00: Afternoon Killzone - Silver Bullet & continuation
                # 15:00 - 15:30: Closing square-off
                cur_t_only = cur_time.time()
                is_kz1 = (dtime(9, 15) <= cur_t_only <= dtime(10, 30))
                is_kz2 = (dtime(13, 30) <= cur_t_only <= dtime(15, 0))

                if is_kz1:
                    # High momentum push + occasional sharp counter-sweep
                    trend_step = day_bias * volatility * 1.2
                    bar_vol = volatility * 1.4
                elif is_kz2:
                    trend_step = day_bias * volatility * 0.9
                    bar_vol = volatility * 1.1
                else:
                    trend_step = 0.0
                    bar_vol = volatility * 0.5  # Consolidation

                # Create 3-candle FVG displacement periodically in Killzones
                if (is_kz1 and bar_in_day in kz1_disp) or (is_kz2 and bar_in_day in kz2_disp):
                    # Strong displacement candle (creates FVG)
                    delta = day_bias * bar_vol * 2.8
                    wick_opp = bar_vol * 0.2
                    wick_trend = bar_vol * 0.3
                else:
                    delta = random.gauss(trend_step, bar_vol)
                    wick_opp = abs(random.gauss(0, bar_vol * 0.5))
                    wick_trend = abs(random.gauss(0, bar_vol * 0.5))

                op = price
                cl = price + delta

                if cl >= op:
                    hi = cl + wick_trend
                    lo = op - wick_opp
                else:
                    hi = op + wick_opp
                    lo = cl - wick_trend

                # Occasional liquidity hunt wick (penetrates previous swings)
                if bar_in_day in sweep_bars:
                    if day_bias > 0:
                        lo -= bar_vol * 1.8  # Sell-side sweep wick
                    else:
                        hi += bar_vol * 1.8  # Buy-side sweep wick

                candles.append(Candle(
                    timestamp=t_sec,
                    open=round(op, 2),
                    high=round(hi, 2),
                    low=round(lo, 2),
                    close=round(cl, 2),
                    volume=random.randint(5000, 45000)
                ))
                price = cl
                cur_time += timedelta(minutes=step_minutes)

        return candles
