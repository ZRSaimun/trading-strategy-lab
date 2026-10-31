"""Opt-in, disconnected, causally issued recency-weighted forecast challenger.

This is an uncalibrated research candidate. It reads only a validated server
journal, writes only forecast events through the existing atomic CAS primitive,
and never reads a quote API, sends an alert, simulates a fill or places an order.
"""
import hashlib
import math

HORIZONS = (1, 3, 12)
HALF_LIFE_SAMPLES = 128
MIN_SAMPLES = 30
MIN_EFFECTIVE_SAMPLES = 20.0
MODEL_VERSION = "jeffreys-decay-utc-phase-v1-hl128-n30-ess20"
EVIDENCE = "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL"


def decayed_training(candles, seconds, horizon):
    """Return (p, eligible_count, effective_n) from fully matured, disjoint labels.

    Each label needs every intervening completed candle. Phase alignment makes
    h-step outcome windows disjoint; it does not make outcomes independent.
    Exponential weights decay by *eligible observation index*, not wall time.
    The final observed candle can settle prior labels, but is never a training
    base for its own future target.
    """
    if (type(seconds) is not int or not 60 <= seconds <= 86400 or seconds % 60
            or type(horizon) is not int or horizon not in HORIZONS
            or type(candles) is not list or len(candles) > 5000):
        raise ValueError("Invalid challenger horizon or candle bounds")
    closes = {}
    last = -1
    for row in candles:
        if type(row) is not dict:
            raise ValueError("Invalid challenger candle")
        start, close = row.get("start"), row.get("close")
        if (type(start) is not int or start < 0 or start % seconds
                or start <= last or type(close) not in (int, float)
                or not math.isfinite(close) or close <= 0):
            raise ValueError("Invalid or revised challenger candle")
        closes[start] = close
        last = start
    outcomes = []
    for start, close in closes.items():
        if (start // seconds) % horizon:
            continue
        if all(start + step * seconds in closes for step in range(1, horizon + 1)):
            outcomes.append(float(closes[start + horizon * seconds] > close))
    n = len(outcomes)
    if n == 0:
        return None, 0, 0.0
    # Scale-free weights prevent underflow and keep fixed, preregistered decay.
    weights = [2.0 ** (-(n - 1 - i) / HALF_LIFE_SAMPLES) for i in range(n)]
    total = math.fsum(weights)
    squares = math.fsum(weight * weight for weight in weights)
    effective = total * total / squares
    probability = (math.fsum(w * y for w, y in zip(weights, outcomes)) + 0.5) / (total + 1.0)
    if not 0.0 < probability < 1.0 or not math.isfinite(effective):
        raise ValueError("Invalid challenger probability")
    return probability, n, effective


class CausalDecayChallenger:
    """Issue a second, frozen model only for the latest persisted candle.

    Invoke *after* a separate authorized completed-candle writer has committed
    its event. No provider authentication or schedule is installed here.
    """

    def __init__(self, store, session_id, identity, max_lag_seconds):
        if type(identity) is not dict or type(max_lag_seconds) is not int:
            raise ValueError("Invalid challenger configuration")
        self.store = store
        self.session_id = session_id
        self.identity = identity.copy()
        self.max_lag_seconds = max_lag_seconds
        self.model_version = MODEL_VERSION

    def issue_for_latest(self, base_start):
        if type(base_start) is not int or base_start < 0:
            raise ValueError("Invalid challenger base")
        snapshot = self.store.load(self.session_id)
        if (type(snapshot) is not dict or snapshot.get("evidence") != EVIDENCE
                or snapshot.get("identity") != self.identity
                or snapshot.get("maxLagSeconds") != self.max_lag_seconds
                or type(snapshot.get("sequence")) is not int
                or type(snapshot.get("events")) is not list
                or snapshot["sequence"] != len(snapshot["events"])):
            raise ValueError("Missing or mismatched validated forecast journal")
        events = snapshot["events"]
        candles = [e for e in events if type(e) is dict and e.get("kind") == "CANDLE"]
        if not candles or candles[-1].get("start") != base_start:
            raise ValueError("Challenger requires latest persisted completed candle")
        issued = {}
        for event in events:
            if type(event) is not dict:
                raise ValueError("Malformed challenger event")
            if event.get("kind") == "FORECAST" and event.get("modelVersion") == MODEL_VERSION and event.get("baseStart") == base_start:
                h = event.get("horizon")
                if type(h) is not int or h in issued:
                    raise ValueError("Duplicate challenger issuance")
                issued[h] = event
        actions = []
        counts, effective_counts, probabilities = {}, {}, {}
        for horizon in HORIZONS:
            p, n, ess = decayed_training(candles, self.identity["seconds"], horizon)
            counts[horizon], effective_counts[horizon] = n, ess
            if n < MIN_SAMPLES or ess < MIN_EFFECTIVE_SAMPLES:
                if horizon in issued:
                    raise ValueError("Challenger issuance violates frozen sample policy")
                continue
            probabilities[horizon] = p
            fid = "dc_" + hashlib.sha256(
                f"{self.session_id}:{MODEL_VERSION}:{base_start}:{horizon}".encode("utf-8")
            ).hexdigest()[:32]
            if horizon in issued:
                if issued[horizon].get("id") != fid or issued[horizon].get("probability") != p:
                    raise ValueError("Challenger restart/model mismatch")
                continue
            actions.append({"kind": "FORECAST", "id": fid, "modelVersion": MODEL_VERSION,
                            "horizon": horizon, "probability": p, "baseStart": base_start})
        if actions:
            if not self.store.append_forecasts_atomic(
                    self.session_id, self.identity, self.max_lag_seconds,
                    snapshot["sequence"], actions):
                raise RuntimeError("Challenger CAS conflict; reload and reconcile")
            snapshot = self.store.load(self.session_id)
            if snapshot is None or snapshot.get("sequence") != len(events) + len(actions):
                raise RuntimeError("Challenger issuance persistence not confirmed")
        return {"status": "UNAUTHENTICATED_DISCONNECTED_RESEARCH", "live": False,
                "alertsEnabled": False, "ordersSubmitted": 0, "sourceAuthenticated": False,
                "modelVersion": MODEL_VERSION, "baseStart": base_start,
                "sequence": snapshot["sequence"], "sampleCounts": counts,
                "effectiveSamples": effective_counts, "probabilities": probabilities}
