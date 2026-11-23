import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// An unrevealed future timestamp must not upgrade an unverified volume
// declaration into apparent evidence for the prior-20 volume gate.
test('future timestamp cannot promote unverified volume source to verified',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture-provider',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 const completed:Bar={time:0,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60};
 const second:Bar={...completed,time:H};
 let firstFutureReads=0,secondFutureReads=0,futureMarketReads=0;
 const forbidden=Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
  field=>[field,{enumerable:true,get:()=>{futureMarketReads++;throw Error('future '+field+' read');}}]
 ));
 const futureOne=Object.defineProperties({},{
  time:{enumerable:true,get:()=>{
   firstFutureReads++;
   source.volumeType='exchange';
   source.volumeVerified=true;
   return 3*H;
  }},
  ...forbidden,
 }) as Bar;
 const futureTwo=Object.defineProperties({},{
  time:{enumerable:true,get:()=>{secondFutureReads++;throw Error('second future timestamp read');}},
  ...forbidden,
 }) as Bar;
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf([completed,second,futureOne,futureTwo],source,2*H),
  /FVG source declaration field changed during declaration snapshot/,
 );
 assert.equal(source.volumeVerified,true);
 assert.equal(source.volumeType,'exchange');
 assert.equal(firstFutureReads,1);
 assert.equal(secondFutureReads,0);
 assert.equal(futureMarketReads,0);
});
