import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic snapshot-integrity test only; no authenticated market data or trading evidence.
test('future timestamp cannot turn completed BID volume into nonfinite evidence',()=>{
 const H=3600;
 const source:FvgSource={datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false};
 const completed:Bar[]=[0,H,2*H].map(time=>({
  time,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60,
 }));
 let timestampReads=0,unrevealedReads=0;
 const future=Object.defineProperties({},{
  time:{enumerable:true,get:()=>{timestampReads++;completed[1].volume=Number.NaN;return 3*H;}},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   key=>[key,{enumerable:true,get:()=>{unrevealedReads++;throw Error('future '+key+' read');}}]
  )),
 }) as Bar;
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf([...completed,future],source,3*H),
  /Hourly research completed candle field changed during snapshot/,
  'completed volume must not be silently converted to missing/unknown after snapshot',
 );
 assert.equal(timestampReads,1);
 assert.equal(unrevealedReads,0,'future market fields must remain unread');
});
