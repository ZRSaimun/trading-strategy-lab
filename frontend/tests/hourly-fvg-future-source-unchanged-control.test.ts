import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Positive control for the future-timestamp provenance mutation regressions.
// An unchanged declaration must not be rejected merely because a future time is inspected.
test('unchanged completed FVG source survives future timestamp preflight without future market reads',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture-provider',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 const first:Bar={time:0,open:100,high:101,low:99,close:100,volume:null,observed_minutes:60};
 const second:Bar={...first,time:H};
 let futureTimeReads=0,futureMarketReads=0;
 const future=Object.defineProperties({},{
  time:{enumerable:true,get:()=>{futureTimeReads++;return 3*H;}},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   field=>[field,{enumerable:true,get:()=>{
    futureMarketReads++;
    throw Error('unrevealed '+field+' accessed');
   }}]
  )),
 }) as Bar;
 assert.doesNotThrow(()=>studyHourlyFvgMidpointAsOf([first,second,future],source,2*H));
 assert.equal(futureTimeReads,1);
 assert.equal(futureMarketReads,0);
 assert.equal(source.volumeVerified,false);
 assert.equal(source.volumeType,'unverified');
});
