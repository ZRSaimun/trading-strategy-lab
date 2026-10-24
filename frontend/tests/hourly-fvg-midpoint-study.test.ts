import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpoint,type FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

const H=3600,BASE=Date.UTC(2026,9,20)/1000;
const source:FvgSource={datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
 instrument:'NSXUSD-CFD',provider:'authorized-test-archive',
 priceSide:'bid',volumeType:'exchange',volumeVerified:true};
const candle=(i:number,open=100,high=102,low=98,close=100,volume:number|null=100):Bar=>({
 time:BASE+i*H,open,high,low,close,volume,observed_minutes:60,
});
function fixture(){
 const bars=Array.from({length:40},(_,i)=>candle(i));
 bars[30]=candle(30,99,100,98,99);
 bars[31]=candle(31,100,102,99,101);
 bars[32]=candle(32,105,106,104,105);
 bars[33]=candle(33,105,106,101,105.5,200);
 bars[34]=candle(34,105.5,107,105,106);
 bars[35]=candle(35,106,108,105,107);
 bars[36]=candle(36,107,111,106,110);
 return bars;
}
const target=(bars:Bar[],s:FvgSource=source)=>{
 const observations=studyHourlyFvgMidpoint(bars,s).observations;
 const found=observations.find(x=>x.formationClosedAt===BASE+33*H);
 assert.ok(found,'expected exact 3-candle FVG');
 return found;
};
test('first bullish midpoint touch has a hypothetical blind limit and later next-open rejection markout',()=>{
 const x=target(fixture());
 assert.equal(x.direction,'BULLISH');
 assert.equal(x.gapLow,100);
 assert.equal(x.gapHigh,104);
 assert.equal(x.midpoint,102);
 assert.equal(x.formationClosedAt,BASE+33*H);
 assert.equal(x.firstTouchClosedAt,BASE+34*H);
 assert.equal(x.gates.midpointTouch,'PASS');
 assert.equal(x.gates.wickRejection,'PASS');
 assert.equal(x.gates.verifiedVolume,'PASS');
 assert.equal(x.gates.strictCandidate,'PASS');
 assert.equal(x.gates.markout,'PASS');
 assert.equal(x.blindMidpointTouch?.entryPrice,102);
 assert.equal(x.confirmedNextOpen?.entryPrice,105.5);
 assert.equal(x.confirmedNextOpen?.entryObservedAt,BASE+34*H);
 assert.equal(x.blindMidpointTouch?.exitObservedAt,BASE+37*H);
 assert.equal(x.confirmedNextOpen?.exitObservedAt,BASE+37*H);
 assert.ok((x.blindMidpointTouch?.grossBps??0)>(x.confirmedNextOpen?.grossBps??0));
 assert.equal(x.eligibleForLiveTrading,false);
});
test('a failed first touch cannot be replaced by a prettier later rejection',()=>{
 const bars=fixture();
 bars[33]=candle(33,105,106,101,102.5,200); // 1st touch, closes lower
 bars[34]=candle(34,105,106,101,105.5,200); // tempting later PASS
 const x=target(bars);
 assert.equal(x.gates.wickRejection,'FAIL');
 assert.equal(x.gates.strictCandidate,'FAIL');
 assert.equal(x.firstTouchClosedAt,BASE+34*H);
 assert.equal(x.confirmedNextOpen,null);
 assert.ok(x.blindMidpointTouch);
});
test('a touch bar is never used as the rejection entry and later prices do not rewrite the signal',()=>{
 const bars=fixture();
 const first=target(bars);
 bars[37]=candle(37,1,2,.5,1);
 bars[38]=candle(38,1,2,.5,1);
 const second=target(bars);
 assert.equal(first.firstTouchClosedAt,second.firstTouchClosedAt);
 assert.equal(first.gates.wickRejection,second.gates.wickRejection);
 assert.equal(first.confirmedNextOpen?.entryPrice,second.confirmedNextOpen?.entryPrice);
 assert.equal(first.confirmedNextOpen?.grossBps,second.confirmedNextOpen?.grossBps);
});
test('unverified, placeholder or insufficient 20-bar volume cannot pass',()=>{
 const bars=fixture();
 const unknown=target(bars,{...source,volumeType:'unverified',volumeVerified:false});
 assert.equal(unknown.gates.verifiedVolume,'INSUFFICIENT_DATA');
 assert.equal(unknown.gates.strictCandidate,'INSUFFICIENT_DATA');
 const zero=fixture();zero[31].volume=0;
 assert.equal(target(zero).gates.verifiedVolume,'INSUFFICIENT_DATA');
 const low=fixture();low[33].volume=120;
 assert.equal(target(low).gates.verifiedVolume,'FAIL');
 assert.equal(target(low).gates.strictCandidate,'FAIL');
});
test('missing 1H bar in pre-touch path is unknown, not a false negative or later cherry-picked touch',()=>{
 const bars=fixture().filter(b=>b.time!==BASE+33*H);
 const x=target(bars);
 assert.equal(x.gates.midpointTouch,'INSUFFICIENT_DATA');
 assert.equal(x.firstTouchClosedAt,null);
 assert.equal(x.blindMidpointTouch,null);
});
test('missing future markout does not fabricate a profit or a losing return',()=>{
 const bars=fixture().slice(0,35);
 const x=target(bars);
 assert.equal(x.gates.wickRejection,'PASS');
 assert.equal(x.gates.markout,'INSUFFICIENT_DATA');
 assert.equal(x.blindMidpointTouch,null);
 assert.equal(x.confirmedNextOpen,null);
});
test('an opening gap through midpoint is not a verified blind limit fill',()=>{
 const bars=fixture();
 bars[33]=candle(33,101,106,100,105.5,200);
 const x=target(bars);
 assert.equal(x.gates.midpointTouch,'INSUFFICIENT_DATA');
 assert.equal(x.blindMidpointTouch,null);
 assert.equal(x.confirmedNextOpen,null);
});
test('hypothetical costs are deducted identically and cannot be confused with broker quotes',()=>{
 const x=target(fixture());
 for(const result of [x.blindMidpointTouch,x.confirmedNextOpen]){
  assert.ok(result);
  assert.deepEqual(result.netBpsByCost.map(r=>r.costBps),[0,5,15]);
  assert.ok(Math.abs(result.netBpsByCost[2].netBps-(result.grossBps-15))<1e-10);
 }
});
test('bearish midpoint rejection uses upper wick and directional next-open markout',()=>{
 const bars=fixture().map(b=>({...b,open:220-b.open,high:220-b.low,
  low:220-b.high,close:220-b.close}));
 const x=target(bars);
 assert.equal(x.direction,'BEARISH');
 assert.equal(x.gates.wickRejection,'PASS');
 assert.equal(x.gates.verifiedVolume,'PASS');
 assert.ok((x.confirmedNextOpen?.grossBps??0)>0);
});
test('invalid source, incomplete candles and unsafe settings fail closed',()=>{
 assert.throws(()=>studyHourlyFvgMidpoint(fixture(),{...source,archiveSha256:'wrong'}),/Invalid source/);
 const bad=fixture();bad[20].observed_minutes=59;
 assert.throws(()=>studyHourlyFvgMidpoint(bad,source),/Invalid, incomplete/);
 const badOrder=fixture();badOrder[22].time=badOrder[21].time;
 assert.throws(()=>studyHourlyFvgMidpoint(badOrder,source),/Invalid, incomplete/);
 assert.throws(()=>studyHourlyFvgMidpoint(fixture(),source,{maxTouchWaitBars:0}),/Invalid source/);
 assert.throws(()=>studyHourlyFvgMidpoint(fixture(),source,{hypotheticalRoundTripCostsBps:[-5]}),/Invalid source/);
});
