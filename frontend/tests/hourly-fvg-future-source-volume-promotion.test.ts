import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// A future timestamp must not upgrade unverified volume provenance in the
// already-frozen declaration, even though future OHLC is never read.
test('future timestamp cannot promote unverified source volume to verified',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 const first:Bar={time:0,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60};
 const second:Bar={time:H,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60};
 let futureTimestampReads=0,futureMarketReads=0;
 const future=Object.defineProperties({},{
  time:{enumerable:true,get:()=>{
   futureTimestampReads++;
   source.volumeVerified=true;
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
  'source verification must remain frozen after the future timestamp read',
 );
 assert.equal(futureTimestampReads,1);
 assert.equal(futureMarketReads,0);
});
