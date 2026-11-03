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
const bars=():Bar[]=>Array.from({length:3},(_,i)=>({
 time:i*H,open:100,high:102,low:98,close:100,volume:0,observed_minutes:60,
}));

test('hourly FVG rejects hidden own-index archive rows in both research paths',()=>{
 for(const index of [0,1,2]){
  const archive=bars();
  Object.defineProperty(archive,index,{
   value:archive[index],enumerable:false,writable:true,configurable:true,
  });
  assert.throws(()=>studyHourlyFvgMidpoint(archive,source),
   /missing or hidden own-index/);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(archive,source,3*H),
   /missing or hidden own-index/);
 }
 const ordinary=bars();
 assert.doesNotThrow(()=>studyHourlyFvgMidpoint(ordinary,source));
 assert.doesNotThrow(()=>studyHourlyFvgMidpointAsOf(ordinary,source,3*H));
});

test('hourly FVG refuses sparse own-index holes even when prototype supplies a candle',()=>{
 for(const index of [0,1,2]){
  const archive=bars();
  const inherited=archive[index];
  delete archive[index];
  const prototype=Object.create(Array.prototype);
  Object.defineProperty(prototype,String(index),{
   value:inherited,enumerable:true,configurable:true,writable:true,
  });
  Object.setPrototypeOf(archive,prototype);
  assert.throws(()=>studyHourlyFvgMidpoint(archive,source),
   /missing or hidden own-index/);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(archive,source,3*H),
   /missing or hidden own-index/);
 }
});
