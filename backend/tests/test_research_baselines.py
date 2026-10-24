import sqlite3
from pathlib import Path
import pytest
from app.research_baselines import backtest, hourly_rows,metrics,evaluate


def test_signal_uses_only_four_previous_closed_hours():
    bars=[{'time':i*3600,'open':100+i,'close':101+i,'high':102+i,'low':99+i,'observed_minutes':60} for i in range(12)]
    result=backtest(bars,strategy='momentum_4h',cost_bps=0)
    assert len(result)==8
    assert result[0]['direction']==1
    newer=[dict(x) for x in bars]
    newer[-1]['close']=112
    assert backtest(newer,strategy='momentum_4h',cost_bps=0)[:-1]==result[:-1]
    assert backtest(newer,strategy='reversion_4h',cost_bps=0)[0]['direction']==-1


def test_costs_and_session_gap():
    bars=[{'time':i*3600,'open':100,'close':100.1+i/1000,'high':101,'low':99,'observed_minutes':60} for i in range(7)]
    base=backtest(bars,strategy='momentum_4h',cost_bps=0)
    expensive=backtest(bars,strategy='momentum_4h',cost_bps=20)
    assert len(base)==len(expensive)==3
    assert all(abs((a['ret']-b['ret'])-.002)<1e-9 for a,b in zip(base,expensive))
    bars[4]['time']+=3600
    assert len(backtest(bars,strategy='momentum_4h',cost_bps=0))<3


def test_hourly_stream_merges_annual_datasets_without_inventing_bars(tmp_path):
    c=sqlite3.connect(tmp_path/'test.db')
    c.executescript('''CREATE TABLE historical_datasets(id TEXT PRIMARY KEY, instrument TEXT,provider TEXT,format TEXT,state TEXT);
    CREATE TABLE historical_candles(dataset_id TEXT,time INT,open REAL,high REAL,low REAL,close REAL);''')
    c.executemany('INSERT INTO historical_datasets VALUES (?,?,?,?,?)', [('a','NSXUSD-CFD','HistData','ascii','READY'),('b','NSXUSD-CFD','HistData','ascii','READY'),('c','XAUUSD','HistData','ascii','READY')])
    c.executemany('INSERT INTO historical_candles VALUES (?,?,?,?,?,?)',[('a',0,1.,2.,.5,1.5),('a',60,1.5,2.5,1,2.),('b',60,1.5,2.5,1,2.),('b',3600,2.,3.,1.5,2.5),('c',0,77,80,75,78)])
    c.commit()
    rows=list(hourly_rows(c,instrument='NSXUSD-CFD',provider='HistData',file_format='ascii'))
    assert rows==[{'time':0,'open':1.,'high':2.5,'low':.5,'close':2.,'observed_minutes':2}, {'time':3600,'open':2.,'high':3.,'low':1.5,'close':2.5,'observed_minutes':1}]
    c.execute('INSERT INTO historical_candles VALUES (?,?,?,?,?,?)',('b',0,88,90,80,89));c.commit()
    with pytest.raises(ValueError,match='Conflicting'):
        list(hourly_rows(c,instrument='NSXUSD-CFD',provider='HistData',file_format='ascii'))
    c.close()


def test_zero_returns_can_still_lose_to_costs():
    vals=[{'time':i,'direction':1,'ret':-.001} for i in range(10)]
    out=metrics(vals)
    assert out['win_rate_pct']==0 and out['mean_return_bps']==-10
    assert out['max_drawdown_pct_hypothetical']>0