"""Disconnected causal forecast issuance atop ForecastEventStore.

No feed authentication, scheduler, network transport, alert, broker or order path.
Caller must independently validate and authorize source receipts. Never replay
historical candles into this prospective journal as if they arrived live.
"""
import hashlib
import math

from .forecast_event_store import ForecastEventStore

HORIZONS = (1, 3, 12)
MODEL_VERSION = "jeffreys-utc-phase-v1"


def _training(candles, seconds, horizon):
    """Use only completed, nonoverlapping UTC-phase-aligned outcomes.

    Require *every* intermediate observed candle, avoiding a false comparison
    across market closure, ingestion outage, or missing data.
    """
    closes = {row["start"]: row["close"] for row in candles}
    successes = trials = 0
    for start, close in closes.items():
        if (start // seconds) % horizon:
            continue
        if all(start + step * seconds in closes for step in range(1, horizon + 1)):
            trials += 1
            successes += closes[start + horizon * seconds] > close
    return successes, trials


class CausalForecastIssuer:
    """Opt-in offline orchestration, NOT an authenticated operational worker.

    A crash after persisting a candle but before issuing forecasts is recovered
    only if the same completed candle is retried before the issuance deadline.
    CAS conflicts fail closed: no unbounded retries, no silent dropped forecasts.
    """
    def __init__(self, store: ForecastEventStore, session_id: str, identity: dict,
                 max_lag_seconds: int, min_samples: int = 30):
        if type(min_samples) is not int or not 30 <= min_samples <= 1000:
            raise ValueError("min_samples must be an integer between 30 and 1000")
        self.store = store
        self.session_id = session_id
        self.identity = identity.copy()
        self.max_lag_seconds = max_lag_seconds
        self.min_samples = min_samples
        self.model_version = f"{MODEL_VERSION}-n{min_samples}"

    def accept(self, start: int, close: float):
        if type(start) is not int or start < 0 or type(close) not in (float, int) or \
                not math.isfinite(close) or close <= 0:
            raise ValueError("Invalid completed-candle observation")
        snapshot = self.store.load(self.session_id)
        if snapshot is not None:
            if snapshot["identity"] != self.identity or snapshot["maxLagSeconds"] != self.max_lag_seconds:
                raise ValueError("Prospective forecast source/lag mismatch")
        events = snapshot["events"] if snapshot else []
        last = next((e for e in reversed(events) if e["kind"] == "CANDLE"), None)
        if last and start <= last["start"]:
            if start != last["start"] or close != last["close"]:
                raise ValueError("Backward or revised prospective candle")
        else:
            expected = snapshot["sequence"] if snapshot else 0
            if not self.store.append(self.session_id, self.identity, self.max_lag_seconds,
                                     expected, {"kind": "CANDLE", "start": start, "close": close}):
                raise RuntimeError("Forecast candle CAS conflict; reload and reconcile")
            snapshot = self.store.load(self.session_id)
            events = snapshot["events"]
        candles = [e for e in events if e["kind"] == "CANDLE"]
        # Do not train on future candles or caller-supplied backfilled history.
        if not candles or candles[-1]["start"] != start:
            raise RuntimeError("Forecast candle persistence not confirmed")
        issued = {(e["modelVersion"], e["horizon"], e["baseStart"])
                  for e in events if e["kind"] == "FORECAST"}
        probabilities = {}
        sample_counts = {}
        for horizon in HORIZONS:
            wins, n = _training(candles, self.identity["seconds"], horizon)
            sample_counts[horizon] = n
            if n < self.min_samples:
                continue
            probabilities[horizon] = (wins + 0.5) / (n + 1)
            if (self.model_version, horizon, start) in issued:
                continue
            fid = "jf_" + hashlib.sha256(
                f"{self.session_id}:{self.model_version}:{start}:{horizon}".encode("utf-8")
            ).hexdigest()[:32]
            action = {"kind": "FORECAST", "id": fid, "modelVersion": self.model_version,
                      "horizon": horizon, "probability": probabilities[horizon],
                      "baseStart": start}
            if not self.store.append(self.session_id, self.identity, self.max_lag_seconds,
                                     snapshot["sequence"], action):
                raise RuntimeError("Forecast issuance CAS conflict; reload and reconcile")
            snapshot = self.store.load(self.session_id)
        return {"status": "UNAUTHENTICATED_DISCONNECTED_RESEARCH", "live": False,
                "alertsEnabled": False, "ordersSubmitted": 0,
                "sequence": snapshot["sequence"], "baseStart": start,
                "modelVersion": self.model_version, "sampleCounts": sample_counts,
                "probabilities": probabilities}
