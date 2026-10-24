import {test} from 'node:test';
import assert from 'node:assert/strict';
import {reviewForecastStability} from '../lib/forecast-stability.ts';
import type {ForecastSample} from '../lib/forecast-audit.ts';
const start=1800000000;
function series(probs:number[],ups:boolean[],horizon:1|3|12=1):ForecastSample[]{
 return probs.map((probability,i)=>({observedAt:start+i*60,evaluatedAt:start+(i+horizon)*60,probability,up:ups[i]}));
}

test('reports insufficient sample rather than pretending two windows exist',()=>{
 const result=reviewForecastStability(series(Array(39).fill(.5),Array(39).fill(true)),1,60,20);
 assert.equal(result.status,'INSUFFICIENT');assert.equal(result.recent,null);
 assert.equal(result.deltaBrier,null);
});
test('detects worse recent calibration versus earlier window and fixed baseline',()=>{
 const p=[...Array(20).fill(.9),...Array(20).fill(.9)];
 const y=[...Array(20).fill(true),...Array(20).fill(false)];
 const result=reviewForecastStability(series(p,y),1,60,20);
 assert.equal(result.status,'REVIEW');
 assert.ok(result.deltaBrier!>.7);
 assert.equal(result.earlier?.count,20);assert.equal(result.recent?.count,20);
 assert.ok(result.recentBrierSkill!<0);
 assert.equal(result.reasons.length,2);
});
test('does not raise a review flag when the last window improves',()=>{
 const result=reviewForecastStability(series([...Array(20).fill(.1),...Array(20).fill(.9)],Array(40).fill(true)),1,60,20);
 assert.equal(result.status,'NO_FLAG');assert.ok(result.deltaBrier!<0);
 assert.ok(result.recent!.brier<.25);
});
test('comparison is prefix causal and never includes later observations',()=>{
 const data=series(Array(60).fill(.6),Array(60).fill(true));
 const before=reviewForecastStability(data.slice(0,40),1,60,20);
 const after=reviewForecastStability(data,1,60,20);
 assert.equal(before.recent!.lastEvaluatedAt,data[39].evaluatedAt);
 assert.equal(after.recent!.lastEvaluatedAt,data[59].evaluatedAt);
 assert.equal(before.recent!.brier,after.recent!.brier);
});
test('handles horizons 3 and 12 without treating overlapping outcomes as independent',()=>{
 for(const h of [3,12] as const){
  const data=series(Array(40).fill(.5),Array(40).fill(true),h);
  const result=reviewForecastStability(data,h,60,20);
  assert.equal(result.status,'NO_FLAG');assert.equal(result.recent!.baselineBrier,.25);
 }
});
test('rejects duplicate, reversed, mixed-horizon and forged invalid probabilities',()=>{
 const data=series(Array(40).fill(.5),Array(40).fill(true));
 assert.throws(()=>reviewForecastStability([...data.slice(0,20),data[19],...data.slice(21)],1,60,20),/Malformed/);
 assert.throws(()=>reviewForecastStability([...data].reverse(),1,60,20),/Malformed/);
 assert.throws(()=>reviewForecastStability(data,3,60,20),/Malformed/);
 assert.throws(()=>reviewForecastStability(data.map((x,i)=>i===1?{...x,probability:1}:x),1,60,20),/Malformed/);
 assert.throws(()=>reviewForecastStability(data.map((x,i)=>i===1?{...x,up:1 as unknown as boolean}:x),1,60,20),/Malformed/);
});
test('rejects invalid settings and does not mutate supplied forecasts',()=>{
 const data=series(Array(40).fill(.5),Array(40).fill(false));
 const before=JSON.stringify(data);
 assert.throws(()=>reviewForecastStability(data,1,59,20),/Invalid/);
 assert.throws(()=>reviewForecastStability(data,1,60,1),/Invalid/);
 assert.throws(()=>reviewForecastStability(data,2 as 1,60,20),/Invalid/);
 reviewForecastStability(data,1,60,20);
 assert.equal(JSON.stringify(data),before);
});

test('refuses to compare the last two windows across an unobserved candle gap',()=>{
 const data=series(Array(40).fill(.8),Array(40).fill(true));
 // An unobserved 30-minute interval separates the two windows. Neither
 // side is a valid adjacent time window despite 40 total evaluations.
 const withGap=data.map((x,i)=>i<20?x:{
  ...x,observedAt:x.observedAt+1800,evaluatedAt:x.evaluatedAt+1800});
 const result=reviewForecastStability(withGap,1,60,20);
 assert.equal(result.status,'INSUFFICIENT');
 assert.equal(result.earlier,null);
 assert.equal(result.recent,null);
 assert.equal(result.deltaBrier,null);
 assert.match(result.reasons.join(' '),/missing or non-contiguous/);
});

test('accepts a contiguous latest comparison after an older historical gap',()=>{
 const data=series(Array(61).fill(.7),Array(61).fill(true));
 const withOlderGap=data.map((x,i)=>i<10?x:{
  ...x,observedAt:x.observedAt+3600,evaluatedAt:x.evaluatedAt+3600});
 // The latest 40 observations (indices 21..60) are consecutive.
 const result=reviewForecastStability(withOlderGap,1,60,20);
 assert.equal(result.status,'NO_FLAG');
 assert.equal(result.earlier?.count,20);
 assert.equal(result.recent?.count,20);
});

test('refuses an incomplete last 200 observations even with enough total samples',()=>{
 const data=series(Array(210).fill(.5),Array(210).fill(false));
 const withGap=data.map((x,i)=>i<120?x:{
  ...x,observedAt:x.observedAt+3600,evaluatedAt:x.evaluatedAt+3600});
 const result=reviewForecastStability(withGap,1,60,100);
 assert.equal(result.status,'INSUFFICIENT');
 assert.match(result.reasons[0],/200/);
});

test('rejects time-shifted forecast samples that do not align with the selected timeframe',()=>{
 const data=series(Array(40).fill(.5),Array(40).fill(true));
 const shifted=data.map(x=>({...x,observedAt:x.observedAt+1,evaluatedAt:x.evaluatedAt+1}));
 assert.throws(()=>reviewForecastStability(shifted,1,60,20),/Malformed/);
});
