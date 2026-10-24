import {test} from 'node:test';
import assert from 'node:assert/strict';
import {analyze,type Bar} from '../lib/research.ts';

const base=1704189600;
const bar=(n:number,low:number,high:number,close=(low+high)/2):Bar=>({
 time:base+n*60,open:(low+high)/2,low,high,close,volume:null,observed_minutes:1,
});
const fvgs=(bars:Bar[],frame='1m')=>analyze(bars,2,frame).filter(x=>x.kind.endsWith('FVG'));

test('a single outside candle sweeping both confirmed swing sides is directionally ambiguous',()=>{
 const bars=[bar(0,9,12),bar(1,8,14),bar(2,6,16),bar(3,8,14),bar(4,9,13),bar(5,4,18,10)];
 const observations=analyze(bars).filter(x=>x.kind.endsWith('SIDE SWEEP'));
 assert.equal(observations.length,0);
 assert.equal(analyze(bars.slice(0,5)).filter(x=>x.kind.endsWith('SIDE SWEEP')).length,0);
});

test('a one-sided confirmed swing sweep still emits only after the observation closes',()=>{
 const bars=[bar(0,9,12),bar(1,8,14),bar(2,6,16),bar(3,8,14),bar(4,9,13),bar(5,4,15,10)];
 const observations=analyze(bars).filter(x=>x.kind.endsWith('SIDE SWEEP'));
 assert.equal(observations.length,1);
 assert.equal(observations[0].kind,'SELL-SIDE SWEEP');
 assert.equal(observations[0].observed_at,bars[5].time+60);
 assert.equal(observations[0].rule_version,'structure-research-v2');
});

test('three consecutive complete minutes allow a formation; an unknown gap does not',()=>{
 const contiguous=[bar(0,7,10),bar(1,10,12),bar(2,13,15)];
 assert.equal(fvgs(contiguous).filter(x=>x.kind==='BULLISH FVG').length,1);
 const gap=[contiguous[0],contiguous[1],bar(32,13,15)];
 assert.equal(fvgs(gap).length,0);
});

test('incomplete intraday aggregate constituent bars cannot create an FVG',()=>{
 const complete=[bar(0,7,10),bar(1,10,12),bar(2,13,15)];
 for(let k=0;k<3;k++){
  const altered=complete.map((x,i)=>i===k?{...x,observed_minutes:0}:x);
  assert.equal(fvgs(altered).length,0);
 }
 const hourly=complete.map((x,i)=>({...x,time:base+i*3600,observed_minutes:60}));
 assert.equal(fvgs(hourly,'1H').length,1);
 hourly[1]={...hourly[1],observed_minutes:59};
 assert.equal(fvgs(hourly,'1H').length,0);
});

test('calendar-month FVG requires adjacent calendar months, including year rollover',()=>{
 const make=(year:number,month:number,low:number,high:number):Bar=>({...bar(0,low,high),time:Date.UTC(year,month,1)/1000,observed_minutes:1000});
 const continuous=[make(2025,10,7,10),make(2025,11,10,12),make(2026,0,13,15)];
 assert.equal(fvgs(continuous,'1M').length,1);
 assert.equal(fvgs([continuous[0],continuous[2],make(2026,1,17,19)],'1M').length,0);
});

test('observations are prefix invariant with no future candle leakage',()=>{
 const bars=[bar(0,9,12),bar(1,8,14),bar(2,6,16),bar(3,8,14),bar(4,9,13),bar(5,4,15,10),bar(6,11,17,16),bar(7,18,21,20)];
 const full=analyze(bars);
 for(let n=1;n<=bars.length;n++){
  const prefix=analyze(bars.slice(0,n));
  assert.deepEqual(prefix,full.filter(x=>x.observed_at<=bars[n-1].time+60));
 }
});
