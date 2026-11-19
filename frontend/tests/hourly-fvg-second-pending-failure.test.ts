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

test('negative infinity in second pending timestamp fails before later future evidence',()=>{
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
   return index===1?Number.NEGATIVE_INFINITY:(index+3)*H;
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
  'negative infinity must stop before later pending timestamp access');
 assert.equal(marketReads,0,'future market evidence must remain unread');
});

test('duplicate second pending timestamp rejects before reading later future evidence',()=>{
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
   return index===1?3*H:(index+3)*H;
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
  'duplicate pending timestamps must stop before later timestamp getters');
 assert.equal(marketReads,0,'duplicate future time cannot authorize market reads');
});

test('descending second pending timestamp fails closed before later future evidence',()=>{
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
   return index===1?2*H:(index+3)*H;
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
  'descending pending timestamps must stop before later timestamp getters');
 assert.equal(marketReads,0,'descending future time cannot authorize market reads');
});

test('valid increasing unrevealed timestamps do not authorize future market-field reads',()=>{
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
  time:{enumerable:true,get:()=>{reads[index]++;return (index+3)*H;}},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   field=>[field,{enumerable:true,get:()=>{
    marketReads++;throw Error('future '+field+' accessed');
   }}]
  )),
 }) as Bar;
 const rows=[completed(0),completed(H),...reads.map((_,index)=>pending(index))];
 const result=studyHourlyFvgMidpointAsOf(rows,source,2*H);
 assert.equal(result.coverage.observedBars,2,
  'only completed rows may contribute to as-of coverage');
 assert.deepEqual(reads,[1,1,1],
  'valid future timestamps may be inspected once for ordering');
 assert.equal(marketReads,0,
  'valid future timestamps must not unlock future OHLC, volume or coverage');
});

test('bar opening exactly at as-of cutoff stays unrevealed even with valid chronological successors',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 const completed=(time:number):Bar=>({
  time,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60,
 });
 const reads=[0,0];
 let futureMarketReads=0;
 const future=(index:number)=>Object.defineProperties({},{
  time:{enumerable:true,get:()=>{reads[index]++;return (index+2)*H;}},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   field=>[field,{enumerable:true,get:()=>{
    futureMarketReads++;throw Error('unclosed '+field+' accessed');
   }}]
  )),
 }) as Bar;
 const result=studyHourlyFvgMidpointAsOf(
  [completed(0),completed(H),future(0),future(1)],source,2*H,
 );
 assert.equal(result.coverage.observedBars,2,
  'bar opening at cutoff cannot count as closed until its own close');
 assert.deepEqual(reads,[1,1],'future timestamps may be checked for order once');
 assert.equal(futureMarketReads,0,'unclosed cutoff-boundary bar must stay unread');
});

test('hour ending exactly at as-of cutoff is included while the next opening hour stays unread',()=>{
 const H=3600;
 const source:FvgSource={
  datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false,
 };
 const completed=(time:number):Bar=>({
  time,open:100,high:101,low:99,close:100,volume:10,observed_minutes:60,
 });
 let timeReads=0,marketReads=0;
 const pending=Object.defineProperties({},{
  time:{enumerable:true,get:()=>{timeReads++;return 3*H;}},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   field=>[field,{enumerable:true,get:()=>{marketReads++;throw Error('future '+field+' accessed');}}]
  )),
 }) as Bar;
 const result=studyHourlyFvgMidpointAsOf(
  [completed(0),completed(H),completed(2*H),pending],source,3*H,
 );
 assert.equal(result.coverage.observedBars,3,
  'the bar closing at cutoff is completed and must count toward coverage');
 assert.equal(timeReads,1,'next unopened bar timestamp may be checked once');
 assert.equal(marketReads,0,'future OHLC, volume and coverage must remain unread');
});

test('off-grid fractional second pending timestamp rejects without inspecting later future evidence',()=>{
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
   return index===1?4*H+0.5:(index+3)*H;
  }},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   field=>[field,{enumerable:true,get:()=>{
    marketReads++;throw Error('future '+field+' accessed');
   }}]
  )),
 }) as Bar;
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf(
   [completed(0),completed(H),...reads.map((_,index)=>pending(index))],
   source,2*H,
  ),
  /Invalid or unordered hourly as-of input timestamp/,
 );
 assert.deepEqual(reads,[1,1,0],
  'off-grid timestamp must stop before later pending timestamps');
 assert.equal(marketReads,0,'future OHLC, volume and coverage remain unread');
});


test('numeric-looking string pending timestamp is rejected without coercion or future market reads',()=>{
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
   return index===1?String(4*H):(index+3)*H;
  }},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   field=>[field,{enumerable:true,get:()=>{
    marketReads++;throw Error('future '+field+' accessed');
   }}]
  )),
 }) as Bar;
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf(
   [completed(0),completed(H),...reads.map((_,index)=>pending(index))],
   source,2*H,
  ),
  /Invalid or unordered hourly as-of input timestamp/,
 );
 assert.deepEqual(reads,[1,1,0],
  'coercible string timestamp must not permit reading later future timestamps');
 assert.equal(marketReads,0,'future OHLC, volume and coverage remain unread');
});


test('second pending timestamp beyond supported 2100 horizon rejects before later evidence',()=>{
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
 const horizon=Date.UTC(2100,0,1)/1000;
 const pending=(index:number)=>Object.defineProperties({},{
  time:{enumerable:true,get:()=>{
   reads[index]++;
   return index===1?horizon+H:(index+3)*H;
  }},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   field=>[field,{enumerable:true,get:()=>{
    marketReads++;throw Error('future '+field+' accessed');
   }}]
  )),
 }) as Bar;
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf(
   [completed(0),completed(H),...reads.map((_,index)=>pending(index))],
   source,2*H,
  ),
  /Invalid or unordered hourly as-of input timestamp/,
 );
 assert.deepEqual(reads,[1,1,0],
  'out-of-horizon future time must stop before later pending timestamp');
 assert.equal(marketReads,0,'future market evidence must remain unread');
});

test('negative-zero second pending timestamp is rejected before later future evidence',()=>{
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
   return index===1?-0:(index+3)*H;
  }},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   field=>[field,{enumerable:true,get:()=>{
    marketReads++;throw Error('future '+field+' accessed');
   }}]
  )),
 }) as Bar;
 assert.throws(
  ()=>studyHourlyFvgMidpointAsOf(
   [completed(0),completed(H),...reads.map((_,index)=>pending(index))],
   source,2*H,
  ),
  /Invalid or unordered hourly as-of input timestamp/,
 );
 assert.deepEqual(reads,[1,1,0],
  'signed-zero pending time must stop before the third timestamp');
 assert.equal(marketReads,0,'unrevealed market and coverage fields remain unread');
});

// A runtime bypass can supply bigint despite the declared numeric Bar type.
// Do not coerce it, even when its magnitude is a valid hourly timestamp.
test('bigint second pending timestamp fails closed before later future evidence',()=>{
 const H=3600;
 const source:FvgSource={datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false};
 const completed=(time:number):Bar=>({time,open:100,high:101,low:99,
  close:100,volume:10,observed_minutes:60});
 const reads=[0,0,0];
 let marketReads=0;
 const pending=(index:number)=>Object.defineProperties({}, {
  time:{enumerable:true,get:()=>{
   reads[index]++;
   return index===1?BigInt(4*H):(index+3)*H;
  }},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   field=>[field,{enumerable:true,get:()=>{
    marketReads++;throw Error('unrevealed '+field+' accessed');
   }}]
  )),
 }) as Bar;
 assert.throws(()=>studyHourlyFvgMidpointAsOf(
  [completed(0),completed(H),...reads.map((_,i)=>pending(i))],source,2*H),
  /Invalid or unordered hourly as-of input timestamp/);
 assert.deepEqual(reads,[1,1,0],
  'bigint timestamp cannot authorize later pending timestamp reads');
 assert.equal(marketReads,0,'unrevealed OHLC, volume and coverage remain unread');
});


test('boxed Number pending timestamp cannot bypass strict numeric chronology',()=>{
 const H=3600;
 const source:FvgSource={datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false};
 const completed=(time:number):Bar=>({time,open:100,high:101,low:99,
  close:100,volume:10,observed_minutes:60});
 const reads=[0,0,0];
 let marketReads=0;
 const pending=(index:number)=>Object.defineProperties({}, {
  time:{enumerable:true,get:()=>{
   reads[index]++;
   return index===1?new Number(4*H):(index+3)*H;
  }},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   field=>[field,{enumerable:true,get:()=>{
    marketReads++;throw Error('unrevealed '+field+' accessed');
   }}]
  )),
 }) as Bar;
 assert.throws(()=>studyHourlyFvgMidpointAsOf(
  [completed(0),completed(H),...reads.map((_,i)=>pending(i))],source,2*H),
  /Invalid or unordered hourly as-of input timestamp/);
 assert.deepEqual(reads,[1,1,0],
  'boxed numeric timestamp cannot authorize later pending timestamp reads');
 assert.equal(marketReads,0,'unrevealed OHLC, volume and coverage remain unread');
});


test('pending timestamp coercion hooks stay uncalled and future evidence unread',()=>{
 const H=3600;
 const source:FvgSource={datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false};
 const completed=(time:number):Bar=>({time,open:100,high:101,low:99,
  close:100,volume:10,observed_minutes:60});
 const reads=[0,0,0];
 let coercionReads=0,marketReads=0;
 const hostile={
  [Symbol.toPrimitive](){coercionReads++;throw Error('coercion executed');},
  valueOf(){coercionReads++;throw Error('valueOf executed');},
  toString(){coercionReads++;throw Error('toString executed');},
 };
 const pending=(index:number)=>Object.defineProperties({}, {
  time:{enumerable:true,get:()=>{reads[index]++;return index===1?hostile:(index+3)*H;}},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   field=>[field,{enumerable:true,get:()=>{
    marketReads++;throw Error('unrevealed '+field+' accessed');
   }}]
  )),
 }) as Bar;
 assert.throws(()=>studyHourlyFvgMidpointAsOf(
  [completed(0),completed(H),...reads.map((_,i)=>pending(i))],source,2*H),
  /Invalid or unordered hourly as-of input timestamp/);
 assert.deepEqual(reads,[1,1,0],'later pending timestamps must remain unread');
 assert.equal(coercionReads,0,'invalid object timestamp must never be coerced');
 assert.equal(marketReads,0,'unrevealed OHLC, volume and coverage remain unread');
});


test('inclusive 2100 UTC horizon remains a valid unrevealed timestamp without future field reads',()=>{
 const H=3600;
 const horizon=Date.UTC(2100,0,1)/1000;
 const source:FvgSource={datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false};
 const completed=(time:number):Bar=>({time,open:100,high:101,low:99,
  close:100,volume:10,observed_minutes:60});
 let timestampReads=0,marketReads=0;
 const pending=Object.defineProperties({},{
  time:{enumerable:true,get:()=>{timestampReads++;return horizon;}},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   field=>[field,{enumerable:true,get:()=>{
    marketReads++;throw Error('unrevealed '+field+' accessed');
   }}]
  )),
 }) as Bar;
 const result=studyHourlyFvgMidpointAsOf(
  [completed(0),completed(H),pending],source,2*H);
 assert.equal(result.coverage.observedBars,2,
  'far-future boundary timestamp must not count as completed evidence');
 assert.equal(timestampReads,1,'boundary timestamp checked once for ordering');
 assert.equal(marketReads,0,'unrevealed market and coverage fields remain unread');
});

test('inclusive horizon followed by out-of-range pending hour fails without future evidence reads',()=>{
 const H=3600, horizon=Date.UTC(2100,0,1)/1000;
 const source:FvgSource={datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
  instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid',
  volumeType:'unverified',volumeVerified:false};
 const completed=(time:number):Bar=>({time,open:100,high:101,low:99,
  close:100,volume:10,observed_minutes:60});
 const reads=[0,0,0];
 let marketReads=0;
 const pending=(index:number)=>Object.defineProperties({},{
  time:{enumerable:true,get:()=>{reads[index]++;
   return index===0?horizon:index===1?horizon+H:horizon+2*H;}},
  ...Object.fromEntries(['open','high','low','close','volume','observed_minutes'].map(
   field=>[field,{enumerable:true,get:()=>{
    marketReads++;throw Error('unrevealed '+field+' accessed');
   }}]
  )),
 }) as Bar;
 assert.throws(()=>studyHourlyFvgMidpointAsOf(
  [completed(0),completed(H),...reads.map((_,i)=>pending(i))],source,2*H),
  /Invalid or unordered hourly as-of input timestamp/);
 assert.deepEqual(reads,[1,1,0],
  'first valid horizon timestamp cannot authorize a later out-of-range hour');
 assert.equal(marketReads,0,'no pending OHLC, volume or coverage may be inspected');
});
