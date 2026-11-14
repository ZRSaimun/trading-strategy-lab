import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpoint,studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

const H=3600;
const source={
 datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
 instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid' as const,
 volumeType:'unverified' as const,volumeVerified:false,
};

// Boolean minute coverage is not an observed minute count. In particular,
// false/true must not be coerced into counts; null/undefined must not be\n// treated as a fully observed hour or silently defaulted to 60.
for(const badCoverage of [false,true,null,undefined]){
 test(`boolean completed-hour coverage ${badCoverage} fails closed without future lookahead`,()=>{
  const makeBars=():Bar[]=>[
   {time:0,open:99,high:100,low:98,close:99,volume:1,observed_minutes:60},
   {time:H,open:101,high:104,low:100,close:103,volume:1,observed_minutes:60},
   {time:2*H,open:103,high:105,low:102,close:104,volume:1,observed_minutes:60},
  ];
  const bars=makeBars();
  let futureReads=0;
  Object.defineProperty(bars[2],'observed_minutes',{
   configurable:true,enumerable:true,
   get(){futureReads++;return badCoverage;},
  });
  const prefix=studyHourlyFvgMidpointAsOf(bars.slice(0,2),source,2*H);
  const before=studyHourlyFvgMidpointAsOf(bars,source,2*H);
  assert.deepEqual(before,prefix,'unclosed future coverage must not affect the prefix');
  assert.equal(futureReads,0,'future coverage must remain unread');
  assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,3*H),
   /observed.minutes|coverage|invalid|complete/i);
  assert.ok(futureReads>0,'completed coverage must be inspected');
  const full=makeBars();
  (full[2] as unknown as {observed_minutes:unknown}).observed_minutes=badCoverage;
  assert.throws(()=>studyHourlyFvgMidpoint(full,source),
   /observed.minutes|coverage|invalid|complete/i);
  assert.ok(studyHourlyFvgMidpoint(makeBars(),source).observations.length>0,
   'valid 60-minute synthetic control should form a gap');
 });
}

// A numeric-looking object must never be coerced into a coverage count.
// Its conversion hooks could have side effects and cannot certify 60 source minutes.
test('object coverage fails closed without coercion or future access',()=>{
 const bars:Bar[]=[
  {time:0,open:99,high:100,low:98,close:99,volume:1,observed_minutes:60},
  {time:H,open:101,high:104,low:100,close:103,volume:1,observed_minutes:60},
  {time:2*H,open:103,high:105,low:102,close:104,volume:1,observed_minutes:60},
 ];
 let futureReads=0;
 let coercions=0;
 const forgedCoverage={valueOf(){coercions++;return 60;},toString(){coercions++;return '60';}};
 Object.defineProperty(bars[2],'observed_minutes',{
  configurable:true,enumerable:true,get(){futureReads++;return forgedCoverage;},
 });
 const prefix=studyHourlyFvgMidpointAsOf(bars.slice(0,2),source,2*H);
 assert.deepEqual(studyHourlyFvgMidpointAsOf(bars,source,2*H),prefix);
 assert.equal(futureReads,0);
 assert.equal(coercions,0);
 assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,3*H),/observed.minutes|coverage|invalid|complete/i);
 assert.ok(futureReads>0);
 assert.equal(coercions,0,'invalid coverage must not invoke conversion hooks');
 assert.throws(()=>studyHourlyFvgMidpoint(bars,source),/observed.minutes|coverage|invalid|complete/i);
 assert.equal(coercions,0);
});
