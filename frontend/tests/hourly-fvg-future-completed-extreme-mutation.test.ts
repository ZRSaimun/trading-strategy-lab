import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Both completed extremes determine whether a historical gap existed.
// An unrevealed timestamp must not retroactively alter either extreme.
for(const field of ['high','low'] as const){
 test(`future timestamp cannot revise completed ${field} before another future read`,()=>{
  const H=3600;
  const source:FvgSource={
   datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
   instrument:'SYNTHETIC',provider:'fixture-provider',priceSide:'bid',
   volumeType:'unverified',volumeVerified:false,
  };
  const completed:Bar={time:0,open:100,high:101,low:99,close:100,volume:null,observed_minutes:60};
  const second:Bar={...completed,time:H};
  let firstFutureReads=0,secondFutureReads=0,futureMarketReads=0;
  const forbidden=Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   key=>[key,{enumerable:true,get:()=>{futureMarketReads++;throw Error('future '+key+' read');}}]
  ));
  const futureOne=Object.defineProperties({},{
   time:{enumerable:true,get:()=>{
    firstFutureReads++;
    if(field==='high') completed.high=101.5;
    else completed.low=98.5;
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
   /completed candle field changed during snapshot/,
  );
  assert.equal(completed[field],field==='high'?101.5:98.5);
  assert.equal(firstFutureReads,1);
  assert.equal(secondFutureReads,0);
  assert.equal(futureMarketReads,0);
 });
}
