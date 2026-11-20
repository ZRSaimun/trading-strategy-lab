import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Multiple unrevealed rows are ordering metadata only, never market evidence.
test('multiple future hourly rows expose only their timestamps at an as-of boundary',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture-provider',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 const first:Bar={time:0,open:100,high:101,low:99,close:100,volume:null,observed_minutes:60};
 const second:Bar={...first,time:H};
 const timeReads=[0,0,0];
 let forbiddenMarketReads=0;
 const future=[3*H,4*H,5*H].map((time,index)=>
  Object.defineProperties({},{
   time:{enumerable:true,get:()=>{timeReads[index]++;return time;}},
   ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
    field=>[field,{enumerable:true,get:()=>{
     forbiddenMarketReads++;
     throw Error('unrevealed future '+field+' accessed');
    }}]
   )),
  }) as Bar
 );
 const result=studyHourlyFvgMidpointAsOf([first,second,...future],source,2*H);
 assert.deepEqual(timeReads,[1,1,1]);
 assert.equal(forbiddenMarketReads,0);
 assert.equal(result.coverage.observedBars,2);
 assert.equal(result.coverage.lastBarClosedAt,2*H);
 assert.equal(result.observations.length,0);
 assert.equal(result.source.volumeVerified,false);
 assert.equal(result.source.volumeType,'unverified');
});
