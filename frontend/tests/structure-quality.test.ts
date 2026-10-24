import {test} from 'node:test';
import assert from 'node:assert/strict';
import {validStructureSegments,type QualityBar} from '../lib/structure-quality.ts';
import {analyze,type Bar} from '../lib/research.ts';
const bar=(time:number,observed_minutes=1):QualityBar=>({time,open:100,high:102,low:99,close:101,observed_minutes});
test('complete minute bars form one run; gap, partial, duplicate and backwards bar break it',()=>{
 const input=[bar(0),bar(60),bar(180),bar(240,0),bar(300),bar(300),bar(360),bar(120),bar(180)];
 assert.deepEqual(validStructureSegments(input,'1m'),[0,0,2,-1,4,5,5,7,7]);
});
test('a partial 5m bucket and malformed OHLC cannot confirm structure',()=>{
 const input=[bar(0,5),bar(300,4),bar(600,5),{...bar(900,5),high:90},bar(1200,5),bar(1500,5)];
 assert.deepEqual(validStructureSegments(input,'5m'),[0,-1,2,-1,4,4]);
});
test('daily weekends and missing hourly candles reset rather than fabricate continuity',()=>{
 assert.deepEqual(validStructureSegments([bar(0,1),bar(86400,1),bar(345600,1)],'1D'),[0,0,2]);
 assert.deepEqual(validStructureSegments([bar(0,60),bar(3600,60),bar(10800,60)],'1H'),[0,0,2]);
});
test('weekly Monday and calendar-month rollover require exact UTC alignment and adjacency',()=>{
 const monday=Date.UTC(2026,9,19)/1000;
 assert.deepEqual(validStructureSegments([bar(monday,1),bar(monday+604800,1),bar(monday+1209600,1)],'1W'),[0,0,0]);
 const jan=Date.UTC(2026,0,1)/1000,feb=Date.UTC(2026,1,1)/1000,apr=Date.UTC(2026,3,1)/1000;
 assert.deepEqual(validStructureSegments([bar(jan),bar(feb),bar(apr)],'1M'),[0,0,2]);
 assert.deepEqual(validStructureSegments([bar(jan+3600)],'1M'),[-1]);
});
test('non-finite prices, bad timestamps, negative observations and unknown frames fail closed',()=>{
 assert.deepEqual(validStructureSegments([{...bar(0),close:Infinity},bar(60),{...bar(120),time:NaN},{...bar(180),observed_minutes:-1},bar(240)],'1m'),[-1,1,-1,-1,4]);
 assert.throws(()=>validStructureSegments([bar(0)],'2D'),/Unsupported/);
});
const marketBar=(n:number,low:number,high:number,close=(low+high)/2,minutes=5):Bar=>({
 time:Date.UTC(2026,9,19)/1000+n*300,open:(low+high)/2,low,high,close,volume:null,observed_minutes:minutes
});
test('a partial breakout and a gap-spanning breakout never create a structural signal',()=>{
 const history=[marketBar(0,7,10),marketBar(1,8,12),marketBar(2,9,15),marketBar(3,8,13),marketBar(4,8,12)];
 const complete=[...history,marketBar(5,11,17,16)];
 assert.ok(analyze(complete,2,'5m').some(d=>d.kind==='BULLISH STRUCTURE BREAK'));
 const partial=[...history,marketBar(5,11,17,16,4)];
 assert.equal(analyze(partial,2,'5m').filter(d=>d.kind==='BULLISH STRUCTURE BREAK').length,0);
 const gap=[...history,marketBar(6,11,17,16)];
 assert.equal(analyze(gap,2,'5m').filter(d=>d.kind==='BULLISH STRUCTURE BREAK').length,0);
});
test('confirmed swing and sweep cannot bridge missing or partial candles',()=>{
 const history=[marketBar(0,10,14),marketBar(1,9,13),marketBar(2,5,12),marketBar(3,8,13),marketBar(4,9,14)];
 const complete=[...history,marketBar(5,4,10,6)];
 assert.ok(analyze(complete,2,'5m').some(d=>d.kind==='SELL-SIDE SWEEP'));
 const partial=[...history,marketBar(5,4,10,6,4)];
 assert.equal(analyze(partial,2,'5m').filter(d=>d.kind==='SELL-SIDE SWEEP').length,0);
 const missing=[...history.slice(0,3),marketBar(4,8,13),marketBar(5,9,14),marketBar(6,4,10,6)];
 assert.equal(analyze(missing,2,'5m').filter(d=>d.kind==='SELL-SIDE SWEEP').length,0);
});
test('completed-bar structure is prefix invariant and only observable at bar close',()=>{
 const bars=[marketBar(0,7,10),marketBar(1,8,12),marketBar(2,9,15),marketBar(3,8,13),marketBar(4,8,12),marketBar(5,11,17,16),marketBar(6,12,18)];
 const full=analyze(bars,2,'5m');
 for(let k=1;k<=bars.length;k++){
  const cutoff=bars[k-1].time+300;
  assert.deepEqual(analyze(bars.slice(0,k),2,'5m'),full.filter(d=>d.observed_at<=cutoff));
 }
});

test('rejects UTC seconds outside JavaScript Date range before checking timeframe alignment',()=>{
 // 8.64e9 seconds is the maximum valid Date instant; the previous bound was
 // incorrectly expressed in milliseconds and accepted this invalid timestamp.
 const invalid=8_640_000_060; // divisible by 60 but outside Date range
 assert.equal(Number.isNaN(new Date(invalid*1000).getTime()),true);
 assert.deepEqual(validStructureSegments([bar(0),bar(invalid),bar(60)],'1m'),[0,-1,2]);
 const market=[{...bar(0),volume:null},{...bar(invalid),volume:null},{...bar(60),volume:null}] as Bar[];
 assert.equal(analyze(market,1,'1m').length,0);
});
