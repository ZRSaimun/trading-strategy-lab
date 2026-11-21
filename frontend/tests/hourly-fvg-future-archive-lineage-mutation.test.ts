import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// An unrevealed future timestamp must not rewrite the identity of the
// completed source archive. Both identifiers are independent integrity gates.
for (const field of ['datasetId','archiveSha256'] as const) {
 test(`future timestamp cannot rewrite completed FVG ${field}`,()=>{
  const H=3600;
  const source:FvgSource={
   datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
   instrument:'SYNTHETIC_GOLD',provider:'fixture-provider',priceSide:'bid',
   volumeType:'unverified',volumeVerified:false,
  };
  const first:Bar={time:0,open:100,high:101,low:99,close:100,volume:null,observed_minutes:60};
  const second:Bar={...first,time:H};
  let futureTimeReads=0,futureMarketReads=0;
  const future=Object.defineProperties({},{
   time:{enumerable:true,get:()=>{
    futureTimeReads++;
    source[field]='c'.repeat(64);
    return 3*H;
   }},
   ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
    name=>[name,{enumerable:true,get:()=>{
     futureMarketReads++;
     throw Error('unrevealed '+name+' accessed');
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
}
