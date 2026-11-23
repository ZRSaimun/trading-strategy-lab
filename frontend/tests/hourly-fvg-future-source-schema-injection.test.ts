import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// A future timestamp may be inspected for ordering, but must not extend the
// previously validated source declaration with unreviewed metadata.
test('future timestamp cannot inject a source identity field after preflight',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture-provider',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 const first:Bar={time:0,open:100,high:101,low:99,close:100,volume:null,observed_minutes:60};
 const second:Bar={...first,time:H};
 let timeReads=0,marketReads=0;
 const future=Object.defineProperties({},{
  time:{enumerable:true,get:()=>{
   timeReads++;
   Object.defineProperty(source,'unreviewedFeedReceipt',{
    configurable:true,enumerable:true,value:'not-authenticated',
   });
   return 3*H;
  }},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   field=>[field,{enumerable:true,get:()=>{
    marketReads++;
    throw Error('unrevealed '+field+' accessed');
   }}]
  )),
 }) as Bar;
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf([first,second,future],source,2*H),
  /FVG as-of source declaration schema changed during timestamp scan/,
 );
 assert.equal(timeReads,1);
 assert.equal(marketReads,0);
 assert.equal(source.volumeVerified,false);
});
