import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// A future timestamp may not downgrade the completed source declaration.
// This tests snapshot consistency, not independent volume authentication.
test('future timestamp cannot revoke completed FVG source volume verification',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'exchange',volumeVerified:true,
 };
 const first:Bar={time:0,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60};
 const second:Bar={...first,time:H};
 let futureTimeReads=0,futureMarketReads=0;
 const future=Object.defineProperties({},{
  time:{enumerable:true,get:()=>{
   futureTimeReads++;
   source.volumeVerified=false;
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
  ()=>studyHourlyFvgMidpointAsOf([first,second,future],source,2*H),
  /FVG source declaration field changed during declaration snapshot/,
 );
 assert.equal(futureTimeReads,1);
 assert.equal(futureMarketReads,0);
});
