"""Offline, read-only hourly baseline research on isolated HistData datasets.

No executions, live signals or broker prices. For research ONLY. Computes
predictive decisions at hour open based strictly on FOUR PRIOR CLOSED HOURS.
Cost scenarios are illustrative, NOT measured historical ask/bid spreads.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
import statistics


def hourly_rows(db: sqlite3.Connection, *, instrument: str, provider: str, file_format: str):
    """Stream source-isolated minute bars, combine only same instrument/provider/format.

    Overlap rows from adjacent ZIPs may occur; exact duplicate OHLC is ignored,
    conflicting same-minute provider bars fail rather than being mixed silently.
    """
    sql = """SELECT c.time,c.open,c.high,c.low,c.close
        FROM historical_candles AS c
        JOIN historical_datasets AS d ON c.dataset_id=d.id
        WHERE d.state='READY' AND d.instrument=? AND d.provider=? AND d.format=?
        ORDER BY c.time ASC, d.id ASC"""
    hour=None; b=None; prev_t=None; prev_v=None
    for t,o,h,l,c in db.execute(sql,(instrument,provider,file_format)):
        if not all(math.isfinite(v) for v in (o,h,l,c)) or l>min(o,c) or h<max(o,c):
            raise ValueError(f'Invalid OHLC at {t}')
        row=(o,h,l,c)
        if t == prev_t:
            if row != prev_v:
                raise ValueError(f'Conflicting OHLC at duplicate time {t}')
            continue
        if prev_t is not None and t<prev_t: raise ValueError('Timestamp order violated')
        prev_t=t;prev_v=row
        key=t//3600*3600
        if key!=hour:
            if b is not None:
                yield b
            hour=key
            b={'time':hour,'open':o,'high':h,'low':l,'close':c,'observed_minutes':1}
        else:
            b['high']=max(b['high'],h)
            b['low']=min(b['low'],l)
            b['close']=c
            b['observed_minutes']+=1
    if b is not None: yield b


def backtest(bars: list[dict], *, strategy: str, cost_bps: float, min_minutes=30):
    """Use *previous* closed H1 bars for decision; trade next hour open to close.

    Hourly OHLC bid-only. Cost_bps is an assumed round-trip price deduction.
    Do NOT call this execution-grade backtesting or a forecast.
    """
    if strategy not in {'momentum_4h','reversion_4h'}: raise ValueError('Unknown rule')
    if cost_bps<0: raise ValueError('cost cannot be negative')
    results=[]
    for i in range(4,len(bars)):
        history=bars[i-4:i]
        current=bars[i]
        window=history+[current]
        if any(b['observed_minutes']<min_minutes or b['open']<=0 for b in window):continue
        if any(b['time']-a['time']!=3600 for a,b in zip(window,window[1:])):continue
        direction=1 if history[-1]['close']>history[0]['close'] else -1
        if strategy=='reversion_4h':direction=-direction
        ret=direction*(current['close']-current['open'])/current['open']-cost_bps/10000
        if ret<=-1: raise ValueError('Hypothetical loss >=100%; leverage assumptions invalid')
        results.append({'time':current['time'],'direction':direction,'ret':ret})
    return results


def metrics(trades: list[dict]):
    if not trades:return {'trades':0}
    values=[t['ret'] for t in trades]
    n=len(values);eq=peak=1.;draw=0.
    for v in values:
        eq*=1+v;peak=max(peak,eq);draw=max(draw,(peak-eq)/peak)
    return {'trades':n,'win_rate_pct':round(100*sum(v>0 for v in values)/n,3),
            'mean_return_bps':round(10000*statistics.mean(values),4),
            'median_return_bps':round(10000*statistics.median(values),4),
            'equity_multiple_hypothetical':round(eq,6),
            'max_drawdown_pct_hypothetical':round(100*draw,3)}


def evaluate(database: str, instruments: list[str], costs: tuple[float,...]=(0,5,20)):
    db=sqlite3.connect(f'file:{Path(database).resolve()}?mode=ro',uri=True)
    report={'method':'H1 entry at open; exit close; previous four closed hours decision; no stopped trades',
            'warnings':['Historical HistData bid OHLC only; ask and spread unavailable',
                        'Fixed hypothetical round-trip costs; NOT historical execution simulation',
                        'One-bar-at-a-time model, ignores financing, slippage, liquidity and margin',
                        'Zero-volume fields are not an order-flow or liquidity indicator',
                        'Do not optimize rules on the 2024-2026 forward-evaluation window',
                        'Excluded intervals with less than 30 observed minutes or nonconsecutive hours'],
            'instruments':[]}
    for instrument in instruments:
        bars=list(hourly_rows(db,instrument=instrument,provider='HistData',file_format='ascii'))
        if not bars:continue
        item={'instrument':instrument,'provider':'HistData','format':'ascii','observed_hours':len(bars),
              'start_utc':datetime.fromtimestamp(bars[0]['time'],timezone.utc).isoformat(),
              'end_utc':datetime.fromtimestamp(bars[-1]['time'],timezone.utc).isoformat(),
              'experiments':[]}
        for strategy in ('momentum_4h','reversion_4h'):
            for bps in costs:
                trades=backtest(bars,strategy=strategy,cost_bps=bps)
                train=[t for t in trades if datetime.fromtimestamp(t['time'],timezone.utc).year<=2023]
                forward=[t for t in trades if datetime.fromtimestamp(t['time'],timezone.utc).year>=2024]
                # These splits are *evaluation labels*, not independently secured holdouts.
                item['experiments'].append({'rule':strategy,'cost_bps_assumed':bps,
                       'all':metrics(trades),'2016_to_2023':metrics(train),'2024_to_2026':metrics(forward),
                       'annual':{str(y):metrics([t for t in trades if datetime.fromtimestamp(t['time'],timezone.utc).year==y])
                                 for y in sorted(set(datetime.fromtimestamp(t['time'],timezone.utc).year for t in trades))}})
        report['instruments'].append(item)
    db.close()
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database',help='Local SQLite research database (opened READ ONLY)')
    parser.add_argument('--instruments',nargs='+',default=['NSXUSD-CFD','WTIUSD-CFD','XAUUSD-OTC'])
    parser.add_argument('--output',type=Path)
    args=parser.parse_args(argv)
    result=evaluate(args.database,args.instruments)
    rendered=json.dumps(result,indent=2,sort_keys=True)+'\n'
    if args.output:
        args.output.write_text(rendered)
        print(f'Wrote {args.output} ({len(rendered)} bytes)')
    else:print(rendered)

if __name__=='__main__':main()