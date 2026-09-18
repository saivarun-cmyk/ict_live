from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True, slots=True)
class MarketTick:
    instrument_key: str
    price: float
    traded_at: datetime
    quantity: int
    previous_close: float


def _varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
        if shift > 63:
            raise ValueError("invalid protobuf varint")
    raise ValueError("truncated protobuf varint")


def _fields(data: bytes) -> Iterator[tuple[int, int, int | bytes]]:
    offset = 0
    while offset < len(data):
        tag, offset = _varint(data, offset)
        number, wire = tag >> 3, tag & 7
        if wire == 0:
            value, offset = _varint(data, offset)
            yield number, wire, value
        elif wire == 1:
            if offset + 8 > len(data):
                raise ValueError("truncated protobuf fixed64")
            yield number, wire, data[offset : offset + 8]
            offset += 8
        elif wire == 2:
            length, offset = _varint(data, offset)
            end = offset + length
            if end > len(data):
                raise ValueError("truncated protobuf message")
            yield number, wire, data[offset:end]
            offset = end
        elif wire == 5:
            if offset + 4 > len(data):
                raise ValueError("truncated protobuf fixed32")
            yield number, wire, data[offset : offset + 4]
            offset += 4
        else:
            raise ValueError(f"unsupported protobuf wire type: {wire}")


def _nested(data: bytes, field_number: int) -> bytes | None:
    return next(
        (
            value
            for number, wire, value in _fields(data)
            if number == field_number and wire == 2 and isinstance(value, bytes)
        ),
        None,
    )


def _ltpc(data: bytes) -> tuple[float, int, int, float]:
    values: dict[int, int | bytes] = {number: value for number, _wire, value in _fields(data)}
    raw_ltp = values.get(1)
    raw_close = values.get(4)
    ltp = struct.unpack("<d", raw_ltp)[0] if isinstance(raw_ltp, bytes) else 0.0
    ltt = int(values.get(2, 0))
    ltq = int(values.get(3, 0))
    close = struct.unpack("<d", raw_close)[0] if isinstance(raw_close, bytes) else 0.0
    return ltp, ltt, ltq, close


def decode_market_feed_v3(payload: bytes) -> dict[str, Any]:
    """Decode the stable LTPC subset of Upstox Market Data Feed V3 protobuf.

    Unknown protobuf fields are ignored, so new optional Upstox fields do not break
    the scanner. Both direct LTPC and full equity/index feed envelopes are handled.
    """
    response_type = 0
    current_ts = 0
    entries: list[bytes] = []
    for number, wire, value in _fields(payload):
        if number == 1 and wire == 0:
            response_type = int(value)
        elif number == 2 and wire == 2 and isinstance(value, bytes):
            entries.append(value)
        elif number == 3 and wire == 0:
            current_ts = int(value)

    names = {0: "initial_feed", 1: "live_feed", 2: "market_info"}
    ticks: list[MarketTick] = []
    for entry in entries:
        key_bytes = _nested(entry, 1)
        feed = _nested(entry, 2)
        if not key_bytes or not feed:
            continue
        ltpc = _nested(feed, 1)
        if ltpc is None:
            full = _nested(feed, 2)
            union = _nested(full, 1) if full else None
            if union is None and full:
                union = _nested(full, 2)
            ltpc = _nested(union, 1) if union else None
        if ltpc is None:
            continue
        price, ltt, quantity, close = _ltpc(ltpc)
        if price <= 0:
            continue
        timestamp_ms = ltt or current_ts
        traded_at = datetime.fromtimestamp(timestamp_ms / 1000, tz=IST)
        ticks.append(MarketTick(key_bytes.decode("utf-8"), price, traded_at, quantity, close))
    return {"type": names.get(response_type, "unknown"), "current_ts": current_ts, "ticks": ticks}
