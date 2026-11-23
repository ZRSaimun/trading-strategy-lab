import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic only. A boolean must not be coerced into a numeric UTC timestamp.
test('boolean second pending timestamp fails closed before reading subsequent future evidence',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 const closed=(time:number):Bar=>({
  time,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60,
 });
 const timeReads=[0,0,0];
 let futureMarketReads=0;
 const pending=(index:number)=>Object.defineProperties({},{
  time:{enumerable:true,get:()=>{
   timeReads[index]++;
   return index===1?true:(index+3)*H;
  }},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   field=>[field,{enumerable:true,get:()=>{
    futureMarketReads++;throw Error('unrevealed '+field+' accessed');
   }}]
  )),
 }) as Bar;
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf(
   [closed(0),closed(H),...timeReads.map((_,index)=>pending(index))],
   source,2*H,
  ),
  /Invalid or unordered hourly as-of input timestamp/,
 );
 assert.deepEqual(timeReads,[1,1,0],
  'invalid boolean chronology must stop before a third future timestamp');
 assert.equal(futureMarketReads,0,
  'future OHLC, volume and minute coverage are never available at cutoff');
});
