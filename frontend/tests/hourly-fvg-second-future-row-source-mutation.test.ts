import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// A later unrevealed row must not be allowed to rewrite evidence already frozen
// for the completed prefix, even when an earlier future row was harmless.
test('second unrevealed timestamp cannot change completed FVG archive identity',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture-provider',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 const first:Bar={time:0,open:100,high:101,low:99,close:100,volume:null,observed_minutes:60};
 const second:Bar={...first,time:H};
 const reads=[0,0];
 let forbiddenMarketReads=0;
 const future=[3*H,4*H].map((time,index)=>Object.defineProperties({},{
  time:{enumerable:true,get:()=>{
   reads[index]++;
   if(index===1) source.archiveSha256='c'.repeat(64);
   return time;
  }},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   field=>[field,{enumerable:true,get:()=>{
    forbiddenMarketReads++;
    throw Error('unrevealed future '+field+' accessed');
   }}]
  )),
 }) as Bar);
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf([first,second,...future],source,2*H),
  /FVG source declaration field changed during declaration snapshot/,
 );
 assert.deepEqual(reads,[1,1]);
 assert.equal(forbiddenMarketReads,0);
 assert.equal(source.volumeVerified,false);
 assert.equal(source.volumeType,'unverified');
});
