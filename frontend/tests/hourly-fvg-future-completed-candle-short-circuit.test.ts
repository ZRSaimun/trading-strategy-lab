import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

test('first unrevealed timestamp mutating completed OHLC stops before second future timestamp',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture-provider',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 const completed:Bar={time:0,open:100,high:101,low:99,close:100,volume:null,observed_minutes:60};
 const next:Bar={...completed,time:H};
 let firstReads=0,secondReads=0,futureMarketReads=0;
 const forbidden=Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
  field=>[field,{enumerable:true,get:()=>{
   futureMarketReads++;
   throw Error('future '+field+' must remain unread');
  }}]
 ));
 const firstFuture=Object.defineProperties({},{
  time:{enumerable:true,get:()=>{
   firstReads++;
   completed.high=102;
   return 3*H;
  }},
  ...forbidden,
 }) as Bar;
 const secondFuture=Object.defineProperties({},{
  time:{enumerable:true,get:()=>{
   secondReads++;
   throw Error('later future timestamp must remain unread');
  }},
  ...forbidden,
 }) as Bar;
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf([completed,next,firstFuture,secondFuture],source,2*H),
  /Hourly research completed candle field changed during snapshot/,
 );
 assert.equal(firstReads,1);
 assert.equal(secondReads,0);
 assert.equal(futureMarketReads,0);
 assert.equal(source.volumeVerified,false);
});
