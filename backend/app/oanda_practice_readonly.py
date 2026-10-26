"""Opt-in, GET-only OANDA v20 fxPractice account/price inspection.

No order endpoints, no live hostname, no trade permissions, no persistence.
The API response is *not* evidence of executable fills or future liquidity.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import re

import httpx

_PRACTICE = "https://api-fxpractice.oanda.com"
_ACCOUNT = re.compile(r"[0-9]{3}-[0-9]{3}-[0-9]{4,12}-[0-9]{3}\Z")
_INSTRUMENT = re.compile(r"[A-Z0-9]{2,12}_[A-Z0-9]{2,12}\Z")
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,12})?\Z")
_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z\Z")
_TRANSACTION = re.compile(r"(?:0|[1-9][0-9]{0,19})\Z")


def _positive(value, name, *, allow_zero=False):
    if type(value) is not str or _DECIMAL.fullmatch(value) is None:
        raise ValueError("Invalid practice " + name)
    number = Decimal(value)
    if number <= 0 and not (allow_zero and number == 0):
        raise ValueError("Invalid practice " + name)
    return number


def _time(value):
    if type(value) is not str or _TIMESTAMP.fullmatch(value) is None:
        raise ValueError("Invalid practice quote time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid practice quote time") from exc
    return parsed


def _identity(account, transaction):
    if type(account) is not str or _ACCOUNT.fullmatch(account) is None:
        raise ValueError("Invalid OANDA v20 practice account identifier")
    if type(transaction) is not str or _TRANSACTION.fullmatch(transaction) is None:
        raise ValueError("Invalid practice transaction cursor")


class OandaPracticeReadOnly:
    """Explicitly enabled read-only practice inspection, no order methods.

    ``transport`` is for deterministic httpx.MockTransport testing. In normal
    operation it is omitted; environment proxies and redirects are disabled.
    """

    def __init__(self, account_id, token, *, enabled=False, transport=None):
        _identity(account_id, "0")
        if type(enabled) is not bool or type(token) is not str or not 1 <= len(token) <= 512 or (
            any(ord(char) < 33 or ord(char) > 126 for char in token)
        ):
            raise ValueError("Invalid practice adapter configuration")
        self._account = account_id
        self._token = token
        self._enabled = enabled
        self._transport = transport

    def __repr__(self):
        return "OandaPracticeReadOnly(enabled=%s, credentials=REDACTED)" % self._enabled

    def _get(self, suffix, params=None):
        if not self._enabled:
            raise PermissionError("Practice network access disabled by default")
        # Only literal allowlisted paths are constructed by the two public methods.
        with httpx.Client(base_url=_PRACTICE, transport=self._transport,
                          follow_redirects=False, trust_env=False, timeout=5.0,
                          headers={"Authorization": "Bearer " + self._token,
                                   "Accept": "application/json"}) as client:
            try:
                response = client.get("/v3/accounts/" + self._account + suffix, params=params)
            except httpx.HTTPError:
                raise ValueError("Practice request failed; no broker state verified") from None
        if response.status_code != 200 or len(response.content) > 262144:
            raise ValueError("Practice response unavailable or oversized")
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Malformed practice response") from None
        if type(payload) is not dict:
            raise ValueError("Malformed practice response")
        return payload

    def account_summary(self):
        """Read account currency/balance/margin, not an order-risk approval."""
        body = self._get("/summary")
        account = body.get("account")
        if type(account) is not dict or account.get("id") != self._account:
            raise ValueError("Practice account identity mismatch")
        transaction = body.get("lastTransactionID")
        _identity(self._account, transaction)
        currency = account.get("currency")
        if type(currency) is not str or re.fullmatch(r"[A-Z]{3}", currency) is None:
            raise ValueError("Invalid practice account currency")
        for key in ("balance", "NAV", "marginUsed"):
            _positive(account.get(key), key, allow_zero=True)
        if account.get("lastTransactionID") != transaction:
            raise ValueError("Practice account transaction cursor mismatch")
        return {"provider": "OANDA_V20_PRACTICE", "account_id": self._account,
                "currency": currency, "balance": account["balance"],
                "NAV": account["NAV"], "margin_used": account["marginUsed"],
                "last_transaction_id": transaction, "practice_api_response_validated": True,
                "independent_source_authentication_verified": False,
                "account_population_reconciled": False, "may_execute_order": False}

    def pricing(self, instruments, *, as_of, max_age_seconds=5):
        """Return only fresh tradeable top-of-book BID/ASK, never a fill quote.

        Caller supplies a UTC receipt-time bound; a returned quote older than
        the bound is withheld, not silently replaced with a newer quote.
        """
        if (type(instruments) is not list or not 1 <= len(instruments) <= 8 or
            any(type(x) is not str or _INSTRUMENT.fullmatch(x) is None for x in instruments) or
            len(set(instruments)) != len(instruments)):
            raise ValueError("Invalid practice instrument population")
        if (not isinstance(as_of, datetime) or as_of.tzinfo is None or
            as_of.utcoffset() is None or type(max_age_seconds) is not int or
            not 0 <= max_age_seconds <= 60):
            raise ValueError("Invalid explicit UTC freshness policy")
        as_of = as_of.astimezone(timezone.utc)
        body = self._get("/pricing", {"instruments": ",".join(instruments)})
        prices = body.get("prices")
        if type(prices) is not list or len(prices) != len(instruments):
            raise ValueError("Incomplete practice pricing population")
        found = {}
        for row in prices:
            if type(row) is not dict:
                raise ValueError("Malformed practice price")
            name = row.get("instrument")
            if name not in instruments or name in found:
                raise ValueError("Duplicate or cross-instrument practice quote")
            if row.get("status") != "tradeable":
                raise ValueError("Non-tradeable practice quote")
            at = _time(row.get("time"))
            # Preserve OANDA's nanosecond timestamp precision. datetime only
            # retains microseconds; truncation alone can admit future quotes.
            fraction = row["time"].partition(".")[2].removesuffix("Z")
            extra_nanoseconds = int((fraction + "000000000")[:9]) % 1000 if fraction else 0
            delta = as_of - at
            age_nanoseconds = ((delta.days * 86400 + delta.seconds) * 1_000_000_000
                               + delta.microseconds * 1000 - extra_nanoseconds)
            if not 0 <= age_nanoseconds <= max_age_seconds * 1_000_000_000:
                raise ValueError("Stale or future practice quote")
            bids, asks = row.get("bids"), row.get("asks")
            if (type(bids) is not list or type(asks) is not list or
                not bids or not asks or len(bids) > 64 or len(asks) > 64 or
                any(type(x) is not dict for x in bids + asks)):
                raise ValueError("Missing or malformed practice quote depth")
            bid = _positive(bids[0].get("price"), "bid")
            ask = _positive(asks[0].get("price"), "ask")
            if bid > ask:
                raise ValueError("Crossed practice quote")
            found[name] = {"instrument": name, "observed_at": row["time"],
                           "bid": str(bid), "ask": str(ask),
                           "spread": str(ask - bid),
                           "source": "OANDA_V20_PRACTICE_UNVERIFIED_EXECUTABILITY",
                           "may_execute_order": False}
        return {"provider": "OANDA_V20_PRACTICE", "account_id": self._account,
                "prices": [found[k] for k in instruments],
                "actual_fill_or_queue_priority_verified": False,
                "cfds_available_for_account_verified": False,
                "may_execute_demo_order": False, "may_execute_real_order": False}
