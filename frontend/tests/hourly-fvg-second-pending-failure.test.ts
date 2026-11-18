import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic only: pending timestamps establish ordering, not market evidence.
test('second pending timestamp failure stops scan before later pending rows or market fields',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 const completed=(time:number):Bar=>({
  time,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60,
 });
 let firstTimeReads=0,secondTimeReads=0,thirdTimeReads=0,marketReads=0;
 const guardedFields={
  get open(){marketReads++;throw Error('pending open accessed');},
  get high(){marketReads++;throw Error('pending high accessed');},
  get low(){marketReads++;throw Error('pending low accessed');},
  get close(){marketReads++;throw Error('pending close accessed');},
  get volume(){marketReads++;throw Error('pending volume accessed');},
  get observed_minutes(){marketReads++;throw Error('pending coverage accessed');},
 };
 const firstPending={
  get time(){firstTimeReads++;return 3*H;},...Object.getOwnPropertyDescriptors(guardedFields),
 };
 // Define accessors explicitly: spreading descriptors as values would not retain getters.
 const pending=(getter:()=>number)=>Object.defineProperties({},{
  time:{enumerable:true,get:getter},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   field=>[field,{enumerable:true,get:()=>{marketReads++;throw Error('pending '+field+' accessed');}}]
  )),
 }) as Bar;
 const rows=[completed(0),completed(H),
  pending(()=>{firstTimeReads++;return 3*H;}),
  pending(()=>{secondTimeReads++;throw Error('second pending timestamp unavailable');}),
  pending(()=>{thirdTimeReads++;return 5*H;})];
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf(rows,source,2*H),
  /second pending timestamp unavailable/,
 );
 assert.equal(firstTimeReads,1);
 assert.equal(secondTimeReads,1);
 assert.equal(thirdTimeReads,0,'later pending timestamps must not be evaluated');
 assert.equal(marketReads,0,'pending market fields must remain unread');
});
