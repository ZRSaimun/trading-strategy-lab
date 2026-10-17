import {test} from 'node:test';
import assert from 'node:assert/strict';
import {backtest,candidates,compare,DEFAULTS} from '../lib/backtest.ts';
import type {Bar} from '../lib/research.ts';
const cfg={...DEFAULTS,lookback:3,atrPeriod:3,barSeconds:60,capital:1000,riskPercent:1,spread:0,slippage:0,commission:0};
const b=(i:number,open=10,high=11,low=9,close=10):Bar=>({time:1700000040+i*60,open,high,low,close,volume:null,observed_minutes:1});
const source=[b(0),b(1),b(2),b(3,10,13,9,12),b(4,12,40,8,13)];
test('candidate only enters next open; ambiguous stop/target resolves stop first',()=>{
 const r=backtest(source,'A',cfg);assert.equal(r.trades.length,1);const t=r.trades[0];assert.equal(t.entryAt,source[4].time);assert.equal(t.candidateAt,source[3].time+60);assert.equal(t.entry,12);assert.match(t.reason,/Stop first/);assert.equal(t.pnl,-10);assert.equal(t.r,-1);assert.equal(r.metrics.maxDrawdown,10);
});
test('net target is 2R after spread, slippage and commissions',()=>{
 const r=backtest([...source.slice(0,4),b(4,12,40,11,13)],'A',{...cfg,spread:.4,slippage:.1,commission:.05});
 assert.equal(r.trades.length,1);assert.ok(Math.abs(r.trades[0].r-2)<1e-10);assert.ok(r.trades[0].costs>0);assert.ok(Math.abs(r.trades[0].pnl-20)<1e-9);
});
test('first range break is never sufficient for revised strategy B or E',()=>{
 assert.equal(candidates(source,'B',cfg).length,0);assert.equal(candidates(source,'E',cfg).length,0);
});
test('candidate stream is prefix invariant and evidence never uses future bars',()=>{
 const bars=[...source,...Array.from({length:30},(_,i)=>b(i+5,13,14,12,13))];
 for(const id of ['A','B','C','D','E'] as const){const prefix=candidates(bars.slice(0,12),id,cfg);assert.deepEqual(candidates(bars,id,cfg).filter(c=>c.index<12),prefix);for(const c of candidates(bars,id,cfg))assert.ok(c.evidence.every(t=>t<=bars[c.index].time))}
});
test('gapped entries and entry beyond invalidation are rejected; final signal cannot enter',()=>{
 const gap=source.map(x=>({...x}));gap[4].time+=60;assert.equal(backtest(gap,'A',cfg).trades.length,0);
 const invalid=[...source.slice(0,4),b(4,8,10,7,9)];assert.equal(backtest(invalid,'A',cfg).trades.length,0);
});
test('reproducible comparisons include zero-trade uncertainty and finite metrics',()=>{
 assert.deepEqual(compare(source,cfg),compare(source,cfg));
 const r=backtest(Array.from({length:10},(_,i)=>b(i)),'B',cfg);assert.equal(r.metrics.trades,0);assert.equal(r.metrics.winRate,null);assert.equal(r.metrics.wilson95,null);assert.equal(r.metrics.profitFactor,null);
 assert.throws(()=>backtest(source,'A',{...cfg,rr:1}));assert.throws(()=>backtest(source.map(x=>({...x,observed_minutes:0})),'A',cfg));
});
test('last-bar candidate is counted rejected without imagined future entry',()=>{
 const bars=[b(0),b(1),b(2),b(3),b(4,10,13,9,12)];const r=backtest(bars,'A',cfg);assert.equal(r.trades.length,0);assert.equal(r.rejections['No next candle for entry'],1);
});

test('revised reversal waits for displacement, shift and a later defended retest',()=>{
 const bars=[b(0),b(1),b(2),b(3,10,11,8,10),b(4,10,13,10,12),b(5,12,13,10.5,12),b(6,12,25,11,20)];
 assert.equal(candidates(bars.slice(0,5),'B',cfg).length,0);
 const signals=candidates(bars,'B',cfg);assert.equal(signals.length,1);assert.equal(signals[0].index,5);
 const report=backtest(bars,'B',cfg);assert.equal(report.trades[0].entryAt,bars[6].time);
 assert.equal(candidates(bars,'E',cfg).length,0);
});

test('unknown holding gap is a conservative stop or worse, not an invented winning path',()=>{
 const bars=[b(0),b(1),b(2),b(3,10,13,9,12),b(4,12,13,11,12),b(7,14,16,13,15)];
 const report=backtest(bars,'A',cfg);assert.match(report.trades[0].reason,/Unknown gap/);assert.equal(report.trades[0].r,-1);
});
