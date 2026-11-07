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

test('Symbol.toPrimitive minute-coverage forgery is rejected without coercion or future price access',()=>{
 const bars:Bar[]=[
  {time:0,open:99,high:100,low:98,close:99,volume:1,observed_minutes:60},
  {time:H,open:101,high:104,low:100,close:103,volume:1,observed_minutes:60},
  {time:2*H,open:103,high:105,low:102,close:104,volume:1,observed_minutes:60},
 ];
 let coercions=0;
 let coverageReads=0;
 let priceReads=0;
 const forged={
  [Symbol.toPrimitive](){coercions++;return 60;},
 };
 Object.defineProperty(bars[2],'observed_minutes',{
  enumerable:true,configurable:true,get(){coverageReads++;return forged;},
 });
 Object.defineProperty(bars[2],'close',{
  enumerable:true,configurable:true,get(){priceReads++;return 104;},
 });
 const prefix=studyHourlyFvgMidpointAsOf(bars.slice(0,2),source,2*H);
 assert.deepEqual(studyHourlyFvgMidpointAsOf(bars,source,2*H),prefix);
 assert.equal(coverageReads,0);
 assert.equal(priceReads,0);
 assert.equal(coercions,0);
 assert.throws(()=>studyHourlyFvgMidpointAsOf(bars,source,3*H),/observed.minutes|coverage|invalid|complete/i);
 assert.ok(coverageReads>0);
 assert.equal(coercions,0,'coverage must be validated by primitive type, not conversion');
 assert.throws(()=>studyHourlyFvgMidpoint(bars,source),/observed.minutes|coverage|invalid|complete/i);
 assert.equal(coercions,0);
});
