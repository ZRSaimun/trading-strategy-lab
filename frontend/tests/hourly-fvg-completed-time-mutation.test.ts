import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic regression: a future timestamp accessor cannot revise the
// chronological identity of a previously completed bar after its snapshot.
test('future timestamp cannot rewrite a completed hourly timestamp',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 const first:Bar={time:0,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60};
 const second:Bar={time:H,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60};
 let pendingTimeReads=0,futureMarketReads=0;
 const pending=Object.defineProperties({},{
  time:{enumerable:true,get:()=>{
   pendingTimeReads++;
   second.time=2*H;
   return 3*H;
  }},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   field=>[field,{enumerable:true,get:()=>{
    futureMarketReads++;
    throw Error('unrevealed '+field+' accessed');
   }}]
  )),
 }) as Bar;
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf([first,second,pending],source,2*H),
  /Hourly research completed candle field changed during snapshot/,
  'a completed time rewrite must fail specifically at the frozen-field integrity guard',
 );
 assert.equal(pendingTimeReads,1);
 assert.equal(futureMarketReads,0);
});
