import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// A future timestamp is only a timing boundary, never permission to rewrite
// the completed prefix's BID-only price-side provenance.
test('future timestamp cannot promote completed BID evidence to ASK',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC_GOLD',provider:'fixture-provider',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 const first:Bar={time:0,open:100,high:101,low:99,close:100,volume:null,observed_minutes:60};
 const second:Bar={time:H,open:100,high:101,low:99,close:100,volume:null,observed_minutes:60};
 let futureTimeReads=0,futureMarketReads=0;
 const future=Object.defineProperties({},{
  time:{enumerable:true,get:()=>{
   futureTimeReads++;
   source.priceSide='ask';
   return 3*H;
  }},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   field=>[field,{enumerable:true,get:()=>{
    futureMarketReads++;
    throw Error('unrevealed '+field+' accessed');
   }}]
  )),
 }) as Bar;
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf([first,second,future],source,2*H),
  /FVG source declaration field changed during declaration snapshot/,
 );
 assert.equal(futureTimeReads,1);
 assert.equal(futureMarketReads,0);
});
