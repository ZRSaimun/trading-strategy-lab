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

test('third pending timestamp failure stops without inspecting pending market evidence',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 const completed=(time:number):Bar=>({
  time,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60,
 });
 const reads=[0,0,0,0];
 let marketReads=0;
 const pending=(index:number, time:number, fail=false)=>Object.defineProperties({},{
  time:{enumerable:true,get:()=>{
   reads[index]++;
   if(fail) throw Error('third pending timestamp unavailable');
   return time;
  }},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   field=>[field,{enumerable:true,get:()=>{marketReads++;throw Error('pending '+field+' accessed');}}]
  )),
 }) as Bar;
 const rows=[completed(0),completed(H),
  pending(0,3*H),pending(1,4*H),
  pending(2,5*H,true),pending(3,6*H)];
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf(rows,source,2*H),
  /third pending timestamp unavailable/,
 );
 assert.deepEqual(reads,[1,1,1,0],
  'timestamps must be visited in order and stop at the failing pending row');
 assert.equal(marketReads,0,'pending OHLC, volume and coverage must remain unread');
});

test('fourth pending timestamp failure leaves fifth pending row and all future market fields unread',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 const completed=(time:number):Bar=>({
  time,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60,
 });
 const reads=[0,0,0,0,0];
 let marketReads=0;
 const pending=(index:number)=>Object.defineProperties({},{
  time:{enumerable:true,get:()=>{
   reads[index]++;
   if(index===3) throw Error('fourth pending timestamp unavailable');
   return (index+3)*H;
  }},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   field=>[field,{enumerable:true,get:()=>{marketReads++;throw Error('pending '+field+' accessed');}}]
  )),
 }) as Bar;
 const rows=[completed(0),completed(H),...reads.map((_,index)=>pending(index))];
 assert.throws(()=>studyHourlyFvgMidpointAsOf(rows,source,2*H),
  /fourth pending timestamp unavailable/);
 assert.deepEqual(reads,[1,1,1,1,0],
  'later pending timestamps must not be read after the fourth failure');
 assert.equal(marketReads,0,'future market and coverage getters must remain unread');
});


test('invalid second pending timestamp fails closed without reading later timestamps or future prices',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 const completed=(time:number):Bar=>({
  time,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60,
 });
 const reads=[0,0,0];
 let marketReads=0;
 const pending=(index:number)=>Object.defineProperties({},{
  time:{enumerable:true,get:()=>{
   reads[index]++;
   return index===1?Number.NaN:(index+3)*H;
  }},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   field=>[field,{enumerable:true,get:()=>{
    marketReads++;throw Error('future '+field+' accessed');
   }}]
  )),
 }) as Bar;
 const rows=[completed(0),completed(H),...reads.map((_,index)=>pending(index))];
 assert.throws(()=>studyHourlyFvgMidpointAsOf(rows,source,2*H),
  /Invalid or unordered hourly as-of input timestamp/);
 assert.deepEqual(reads,[1,1,0],
  'invalid timestamp must stop before later pending timestamps');
 assert.equal(marketReads,0,'invalid future time cannot authorize future market reads');
});

test('nonfinite positive infinity in a pending timestamp fails before any later future evidence',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 const completed=(time:number):Bar=>({
  time,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60,
 });
 const reads=[0,0,0];
 let marketReads=0;
 const pending=(index:number)=>Object.defineProperties({},{
  time:{enumerable:true,get:()=>{
   reads[index]++;
   return index===1?Number.POSITIVE_INFINITY:(index+3)*H;
  }},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   field=>[field,{enumerable:true,get:()=>{
    marketReads++;throw Error('future '+field+' accessed');
   }}]
  )),
 }) as Bar;
 const rows=[completed(0),completed(H),...reads.map((_,index)=>pending(index))];
 assert.throws(()=>studyHourlyFvgMidpointAsOf(rows,source,2*H),
  /Invalid or unordered hourly as-of input timestamp/);
 assert.deepEqual(reads,[1,1,0],
  'nonfinite pending timestamp must prevent later future timestamp reads');
 assert.equal(marketReads,0,'nonfinite future time cannot authorize future market reads');
});
