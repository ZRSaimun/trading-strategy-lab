import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// An unrevealed row must not retroactively certify a completed hour as fully covered.
test('future timestamp injecting completed minute coverage fails before later future reads',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture-provider',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 const first:Bar={time:0,open:100,high:101,low:99,close:100,volume:null,observed_minutes:59};
 const second:Bar={...first,time:H};
 let firstFutureReads=0;
 let secondFutureReads=0;
 let futureMarketReads=0;
 const forbidden=Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
  field=>[field,{enumerable:true,get:()=>{futureMarketReads++;throw Error('future '+field+' read');}}]
 ));
 const futureOne=Object.defineProperties({},{
  time:{enumerable:true,get:()=>{
   firstFutureReads++;
   second.observed_minutes=60;
   return 3*H;
  }},
  ...forbidden,
 }) as Bar;
 const futureTwo=Object.defineProperties({},{
  time:{enumerable:true,get:()=>{secondFutureReads++;throw Error('second future timestamp read');}},
  ...forbidden,
 }) as Bar;
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf([first,second,futureOne,futureTwo],source,2*H),
  /Hourly research completed candle field changed during snapshot/,
 );
 assert.equal(firstFutureReads,1);
 assert.equal(secondFutureReads,0);
 assert.equal(futureMarketReads,0);
 assert.equal(source.volumeVerified,false);
});
