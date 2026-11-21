import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic integrity regression only: no market prices, source authentication or profitability.
test('future timestamp cannot revise first completed hourly BID close',()=>{
 const H=3600;
 const source:FvgSource={datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false};
 const first:Bar={time:0,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60};
 const second:Bar={time:H,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60};
 let timestampReads=0,unrevealedMarketReads=0;
 const pending=Object.defineProperties({},{
  time:{enumerable:true,get:()=>{timestampReads++;first.close=100.5;return 2*H;}},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   field=>[field,{enumerable:true,get:()=>{unrevealedMarketReads++;throw Error('future '+field+' read');}}]
  )),
 }) as Bar;
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf([first,second,pending],source,2*H),
  /Hourly research completed candle field changed during snapshot/,
  'first completed BID close revision must fail closed',
 );
 assert.equal(timestampReads,1,'only future timestamp chronology may be inspected');
 assert.equal(unrevealedMarketReads,0,'unrevealed OHLC, volume and coverage cannot become evidence');
});
