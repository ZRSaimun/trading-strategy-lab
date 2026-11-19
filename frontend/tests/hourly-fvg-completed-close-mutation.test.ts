import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic integrity regression: no market data or executable fill evidence.
test('future timestamp cannot retroactively rewrite completed BID close',()=>{
 const H=3600;
 const source:FvgSource={datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false};
 const completed=(time:number):Bar=>({
  time,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60,
 });
 const first=completed(0),second=completed(H);
 let firstFutureTimeReads=0,laterTimeReads=0,unrevealedMarketReads=0;
 const pending=(timeGetter:()=>number)=>Object.defineProperties({},{
  time:{enumerable:true,get:timeGetter},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   field=>[field,{enumerable:true,get:()=>{
    unrevealedMarketReads++;
    throw Error('Unrevealed '+field+' accessed');
   }}]
  )),
 }) as Bar;
 const future=pending(()=>{
  firstFutureTimeReads++;
  second.close=100.5; // valid OHLC, but not the original completed snapshot
  return 3*H;
 });
 const later=pending(()=>{laterTimeReads++;return 4*H;});
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf([first,second,future,later],source,2*H),
  /Hourly research completed candle field changed during snapshot/,
 );
 assert.equal(firstFutureTimeReads,1);
 assert.equal(laterTimeReads,0,'reject mutation before reading later future timestamps');
 assert.equal(unrevealedMarketReads,0,'future market fields cannot become evidence');
});
