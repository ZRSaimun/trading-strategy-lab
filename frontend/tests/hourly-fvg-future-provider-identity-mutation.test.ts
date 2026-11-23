import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Future data may not retroactively relabel the provider of completed BID evidence.
test('future timestamp cannot replace the completed source provider identity',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture-original',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 const first:Bar={time:0,open:100,high:101,low:99,close:100,volume:null,observed_minutes:60};
 const second:Bar={time:H,open:100,high:101,low:99,close:100,volume:null,observed_minutes:60};
 let futureTimestampReads=0,futureMarketReads=0;
 const future=Object.defineProperties({},{
  time:{enumerable:true,get:()=>{
   futureTimestampReads++;
   source.provider='fixture-substituted';
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
 assert.equal(futureTimestampReads,1);
 assert.equal(futureMarketReads,0);
});
