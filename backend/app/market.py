"""Strict UTC one-minute import and observed-only aggregation; never fills gaps."""
import csv
import io
import math
from datetime import datetime, timezone

TIMEFRAMES = {"1m":60,"3m":180,"5m":300,"15m":900,"30m":1800,
              "1H":3600,"2H":7200,"4H":14400,"1D":86400,"1W":604800,"1M":0}

def parse_csv(raw: str):
    rows = []
    seen = set()
    reader = csv.DictReader(io.StringIO(raw))
    if not {"time","open","high","low","close"}.issubset(reader.fieldnames or []):
        raise ValueError("Required headers: time,open,high,low,close; optional volume")
    for n, row in enumerate(reader, 2):
        if len(rows) >= 100000:
            raise ValueError("Maximum 100,000 rows per import")
        try:
            dt = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
            if dt.tzinfo is None:
                raise ValueError("Timezone required")
            t = int(dt.timestamp())
            if dt.second or dt.microsecond or t % 60:
                raise ValueError("Only minute-aligned one-minute bars accepted")
            if t in seen:
                raise ValueError("Duplicate timestamp")
            if rows and t <= rows[-1]["time"]:
                raise ValueError("Rows must be chronological")
            o,h,l,c = [float(row[k]) for k in ("open","high","low","close")]
            v = float(row["volume"]) if row.get("volume", "").strip() else None
            if not all(math.isfinite(x) for x in (o,h,l,c)) or l > min(o,c) or h < max(o,c) or l > h:
                raise ValueError("Invalid OHLC")
            if v is not None and (not math.isfinite(v) or v < 0):
                raise ValueError("Invalid volume")
            seen.add(t)
            rows.append(dict(time=t,open=o,high=h,low=l,close=c,volume=v))
        except (ValueError, TypeError, KeyError) as e:
            raise ValueError(f"Row {n}: {e}") from e
    if not rows:
        raise ValueError("CSV contains no candles")
    return rows

def bucket(t, timeframe):
    dt = datetime.fromtimestamp(t, timezone.utc)
    if timeframe == "1M":
        return int(dt.replace(day=1,hour=0,minute=0,second=0).timestamp())
    if timeframe == "1W":
        return (t - 345600) // 604800 * 604800 + 345600  # Monday UTC
    seconds = TIMEFRAMES[timeframe]
    return t // seconds * seconds

def aggregate(rows, timeframe):
    groups = {}
    for r in rows:
        t = bucket(r["time"], timeframe)
        if t not in groups:
            groups[t] = dict(r, time=t, observed_minutes=1)
        else:
            b = groups[t]
            b.update(high=max(b["high"],r["high"]),low=min(b["low"],r["low"]),close=r["close"],
                     volume=b["volume"]+r["volume"] if b["volume"] is not None and r["volume"] is not None else None,
                     observed_minutes=b["observed_minutes"]+1)
    return list(groups.values())
