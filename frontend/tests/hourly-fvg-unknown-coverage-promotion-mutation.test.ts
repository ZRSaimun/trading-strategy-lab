import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic archive-integrity regression, not authenticated market evidence.
test('future timestamp cannot promote unknown completed minute coverage to full coverage',()=>{
 const H=3600;
 const source:FvgSource={datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false};
 const bars:Bar[]=[0,H,2*H].map(time=>({
  time,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60,
 }));
 (bars[1] as Bar & {observed_minutes:number|null}).observed_minutes=null;
 let timestampReads=0,unrevealedMarketReads=0;
 const future=Object.defineProperties({},{
  time:{enumerable:true,get:()=>{timestampReads++;bars[1].observed_minutes=60;return 3*H;}},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   field=>[field,{enumerable:true,get:()=>{unrevealedMarketReads++;throw Error('future '+field+' read');}}]
  )),
 }) as Bar;
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf([...bars,future],source,3*H),
  /Hourly research completed candle field changed during snapshot/,
  'unknown-to-complete coverage promotion must fail closed',
 );
 assert.equal(timestampReads,1);
 assert.equal(unrevealedMarketReads,0);
});
