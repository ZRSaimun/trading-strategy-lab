import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic fixture only: this tests evidence immutability, not volume provenance.
test('pending timestamp cannot revise completed hourly volume after as-of snapshot',()=>{
 const H=3600;
 const source:FvgSource={datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false};
 const first:Bar={time:0,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60};
 const second:Bar={time:H,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60};
 let timeReads=0,unrevealedReads=0;
 const pending=Object.defineProperties({},{
  time:{enumerable:true,get:()=>{timeReads++;second.volume=11;return 2*H;}},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   field=>[field,{enumerable:true,get:()=>{unrevealedReads++;throw Error('future '+field+' read');}}]
  )),
 }) as Bar;
 assert.throws(()=>studyHourlyFvgMidpointAsOf([first,second,pending],source,2*H),
  /snapshot|mutat|changed|integrity/i,
  'completed volume must not be silently changed by unrevealed timestamp inspection');
 assert.equal(timeReads,1,'future timestamp inspected for chronology once');
 assert.equal(unrevealedReads,0,'future OHLC, volume and coverage must remain unread');
});
