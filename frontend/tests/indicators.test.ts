import test from 'node:test';
import assert from 'node:assert/strict';
import {calculateIndicators,ema,sma,volumeAvailable,type IndicatorBar} from '../lib/indicators.ts';
const bar=(close:number,time=1704067200,volume:number|null=2):IndicatorBar=>({time,open:close,high:close+1,low:close-1,close,volume});
const sequence=(n:number)=>Array.from({length:n},(_,i)=>bar(i+1,1704067200+i*60));
const near=(actual:number|null,expected:number)=>assert.ok(actual!==null&&Math.abs(actual-expected)<1e-9,`${actual} != ${expected}`);
test('SMA warmup and SMA-seeded EMA have independent known values',()=>{
 assert.deepEqual(sma([1,2,3,6,4],3),[null,null,2,11/3,13/3]);
 assert.deepEqual(ema([1,2,3,6,4],3),[null,null,2,4,4]);
 assert.throws(()=>sma([1],0));assert.throws(()=>ema([1],1.5));
});
test('Wilder RSI handles increasing, decreasing and flat closes without infinities',()=>{
 const rising=calculateIndicators(sequence(40),'tick');assert.equal(rising.rsi[13],null);assert.equal(rising.rsi[14],100);
 assert.equal(calculateIndicators(sequence(40).map(b=>({...b,close:-b.close})),'tick').rsi[39],0);
 assert.equal(calculateIndicators(sequence(40).map(b=>({...b,close:5})),'tick').rsi[39],50);
 // Wilder's standard 14-period seed example: avg gain .2385714, avg loss .1.
 const prices=[44.34,44.09,44.15,43.61,44.33,44.83,45.10,45.42,45.84,46.08,45.89,46.03,45.61,46.28,46.28];
 near(calculateIndicators(prices.map((c,i)=>bar(c,1704067200+i*60)),'tick').rsi[14],70.46413502109705);
});
test('ATR includes gaps and Wilder smoothing; Bollinger uses population deviation',()=>{
 const bars=Array.from({length:15},(_,i)=>bar(10,1704067200+i*60));bars[14]=bar(20,bars[14].time);
 const r=calculateIndicators(bars,'tick');assert.equal(r.atr[12],null);near(r.atr[13],2);near(r.atr[14],(26+11)/14);
 const b=calculateIndicators(sequence(20),'tick');near(b.sma[19],10.5);near(b.upper[19],10.5+2*Math.sqrt(33.25));near(b.lower[19],10.5-2*Math.sqrt(33.25));
});
test('MACD and signal warmups are respected and linear sequence has known steady difference',()=>{
 const r=calculateIndicators(sequence(50),'tick');assert.equal(r.macd[24],null);near(r.macd[25],7);assert.equal(r.signal[32],null);near(r.signal[33],7);near(r.histogram[33],0);
});
test('VWAP resets at London midnight in summer and winter; zero and missing volume stay unavailable',()=>{
 for(const dates of [['2026-07-01T22:59:00Z','2026-07-01T23:00:00Z'],['2026-01-01T23:59:00Z','2026-01-02T00:00:00Z']]){
  const bars=dates.map((d,i)=>bar(10+i*10,Date.parse(d)/1000));const r=calculateIndicators(bars,'exchange');assert.deepEqual(r.vwap,[10,20]);
 }
 const r=calculateIndicators([bar(10,1704067200,1),bar(20,1704067260,3)],'tick');near(r.vwap[1],17.5);
 assert.equal(calculateIndicators([bar(10,1704067200,0)],'tick').vwap[0],null);
 assert.equal(volumeAvailable([bar(10,1704067200,null)],'exchange'),false);assert.equal(volumeAvailable([bar(10)],'none'),false);
});
test('every indicator is invariant to future candles during historical replay',()=>{
 const bars=sequence(80),full=calculateIndicators(bars,'exchange');
 for(const n of [1,14,20,26,34,50]){
  const prefix=calculateIndicators(bars.slice(0,n),'exchange');
  for(const key of ['sma','ema','upper','lower','rsi','atr','macd','signal','histogram','vwap'] as const)assert.deepEqual(prefix[key],full[key].slice(0,n),key+' at '+n);
 }
});

test('a later missing volume never changes earlier VWAP and invalidates only its London day',()=>{
 const bars=[bar(10,1704067200,2),bar(20,1704067260,null),bar(30,1704067320,3),bar(40,1704153600,2)];
 const full=calculateIndicators(bars,'tick');assert.deepEqual(full.vwap,[10,null,null,40]);
 for(let n=1;n<=bars.length;n++)assert.deepEqual(calculateIndicators(bars.slice(0,n),'tick').vwap,full.vwap.slice(0,n));
});
