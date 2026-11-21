import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// The first future timestamp may be inspected for as-of filtering, but a
// declaration mutation must fail before a second future row is touched.
test('first future source mutation fails before inspecting later future timestamps',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture-provider',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 const first:Bar={time:0,open:100,high:101,low:99,close:100,volume:null,observed_minutes:60};
 const second:Bar={...first,time:H};
 let firstTimestampReads=0;
 let secondTimestampReads=0;
 let futureMarketReads=0;
 const marketFields=Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
  field=>[field,{enumerable:true,get:()=>{
   futureMarketReads++;
   throw Error('unrevealed future '+field+' accessed');
  }}]
 ));
 const futureOne=Object.defineProperties({},{
  time:{enumerable:true,get:()=>{
   firstTimestampReads++;
   source.provider='retroactive-provider';
   return 3*H;
  }},
  ...marketFields,
 }) as Bar;
 const futureTwo=Object.defineProperties({},{
  time:{enumerable:true,get:()=>{
   secondTimestampReads++;
   throw Error('later future timestamp should not be read');
  }},
  ...marketFields,
 }) as Bar;
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf([first,second,futureOne,futureTwo],source,2*H),
  /FVG source declaration field changed during declaration snapshot/,
 );
 assert.equal(firstTimestampReads,1);
 assert.equal(secondTimestampReads,0);
 assert.equal(futureMarketReads,0);
 assert.equal(source.volumeVerified,false);
 assert.equal(source.volumeType,'unverified');
});
