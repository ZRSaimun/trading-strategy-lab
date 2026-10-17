# Distinct research identities. These are not licensed feed mappings.
INSTRUMENTS = [
 {"id":"XAUUSD-TD","symbol":"XAU/USD","name":"Gold · Twelve Data historical API (requires entitlement)","asset_class":"metal","venue":"Twelve Data source","currency":"USD","precision":2},
 {"id":"XAUUSD-IMPORT","symbol":"XAUUSD","name":"Gold · user CSV","asset_class":"metal","venue":"User-declared OTC source","currency":"USD","precision":2},
 {"id":"NDX-IMPORT","symbol":"NDX","name":"Nasdaq-100 cash index · user CSV","asset_class":"index","venue":"User-declared cash index source","currency":"USD","precision":2},
 {"id":"NQ-IMPORT","symbol":"NQ","name":"Nasdaq futures · contract required (disabled)","asset_class":"futures","venue":"CME","currency":"USD","precision":2,"disabled":True},
]
# Futures imports stay disabled until explicit contract metadata and expiry handling exist.
