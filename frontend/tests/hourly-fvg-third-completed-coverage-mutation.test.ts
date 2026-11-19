import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic snapshot-integrity regression, not authenticated source coverage.
test('future timestamp cannot revise third completed hourly BID minute coverage',()=>{
 const H=3600;
 const source:FvgSource={datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false};
 const bars:Bar[]=[0,H,2*H].map(time=>({
  time,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60,
 }));
 let timestampReads=0,unrevealedMarketReads=0;
 const future=Object.defineProperties({},{
  time:{enumerable:true,get:()=>{timestampReads++;bars[2].observed_minutes=59;return 3*H;}},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   field=>[field,{enumerable:true,get:()=>{unrevealedMarketReads++;throw Error('future '+field+' read');}}]
  )),
 }) as Bar;
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf([...bars,future],source,3*H),
  /Hourly research completed candle field changed during snapshot/,
  'third completed hourly coverage revision must fail closed',
 );
 assert.equal(timestampReads,1,'only unrevealed timestamp is inspected');
 assert.equal(unrevealedMarketReads,0,'future OHLC, volume and coverage remain unread');
});
