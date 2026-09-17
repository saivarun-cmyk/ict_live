"""Killzone time window checks (IST timezone)."""
from datetime import datetime, time
import zoneinfo

IST = zoneinfo.ZoneInfo("Asia/Kolkata")

def parse_session(session_str: str) -> Tuple[time, time]:
    """Parses session string '0915-1030' or '09:15-10:30'."""
    clean = session_str.replace(":", "").strip()
    start_str, end_str = clean.split("-")
    start_time = time(int(start_str[:2]), int(start_str[2:]))
    end_time = time(int(end_str[:2]), int(end_str[2:]))
    return start_time, end_time

def is_in_session(dt: datetime, session_str: str) -> bool:
    """Checks if timestamp in IST falls between session start and end."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=zoneinfo.ZoneInfo("UTC")).astimezone(IST)
    else:
        dt = dt.astimezone(IST)
    
    t = dt.time()
    start_t, end_t = parse_session(session_str)
    return start_t <= t <= end_t
