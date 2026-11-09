import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic BID geometry only; no authenticated quote or volume provenance.
const H=3600;
const source={datasetId:'a'.repeat(64),archiveSha256:'b'.repeat(64),
 instrument:'SYNTHETIC',provider:'fixture',priceSide:'bid' as const,
 volumeType:'unverified' as const,volumeVerified:false};

for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending ${direction} midpoint touch cannot override previously exposed middle-hour censor`,()=>{
  const bull=direction==='BULLISH';
  const bars:Bar[]=Array.from({length:21},(_,i)=>({
   time:i*H,open:bull?100:101,high:bull?101:102,
   low:bull?99:100,close:bull?100:101,volume:10,observed_minutes:60,
  }));
  bars.push(...(bull?[
   {time:21*H,open:102,high:105,low:101,close:104,volume:10,observed_minutes:60},
   {time:22*H,open:104,high:106,low:103,close:105,volume:10,observed_minutes:60},
   {time:23*H,open:104,high:105,low:103,close:104,volume:10,observed_minutes:60},
   {time:25*H,open:104,high:105,low:103,close:104,volume:10,observed_minutes:60},
  ]:[
   {time:21*H,open:99,high:100,low:96,close:97,volume:10,observed_minutes:60},
   {time:22*H,open:97,high:98,low:95,close:96,volume:10,observed_minutes:60},
   {time:23*H,open:96,high:97,low:95,close:96,volume:10,observed_minutes:60},
   {time:25*H,open:96,high:97,low:95,close:96,volume:10,observed_minutes:60},
  ]));
  const prefix=studyHourlyFvgMidpointAsOf(bars,source,26*H);
  let reads=0;
  const forbidden=():number=>{reads++;throw Error('unclosed touch field accessed');};
  const pending={time:26*H,
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},get observed_minutes(){return forbidden();},
  } as Bar;
  const actual=studyHourlyFvgMidpointAsOf([...bars,pending],source,26*H);
  assert.deepEqual(actual,prefix);
  // Multiple not-yet-eligible future candles cannot turn a historical
  // missing-hour censor into an observed first touch. Neither accessor may
  // be consulted even when the archive extends beyond the immediate hour.
  const fartherPending=Object.defineProperties({}, {...Object.getOwnPropertyDescriptors(pending),
   time:{value:27*H,enumerable:true,configurable:true,writable:true},
  }) as Bar;
  assert.deepEqual(studyHourlyFvgMidpointAsOf([...bars,pending,fartherPending],source,26*H),prefix);
  assert.equal(reads,0);
  // An intrabar timestamp is not a completed hourly close: reject it before
  // consulting any pending price, volume or minute-coverage accessor.
  assert.throws(()=>studyHourlyFvgMidpointAsOf([...bars,pending],source,26*H+H/2),
   /Invalid UTC hourly as-of close/);
  assert.equal(reads,0);
  // A malformed future timestamp cannot be silently dropped to make an
  // incomplete source archive appear complete. Reject before touching OHLC.
  const malformed=Object.defineProperties({}, {...Object.getOwnPropertyDescriptors(pending),
   time:{value:Number.NaN,enumerable:true,configurable:true,writable:true},
  }) as Bar;
  assert.throws(()=>studyHourlyFvgMidpointAsOf([...bars,malformed],source,26*H));
  assert.equal(reads,0);
  // An integer-valued future timestamp outside the safe epoch range must
  // fail before accessing any pending OHLC/volume/coverage getter. Reject
  // both signs of infinity as well; none is a missing-hour observation.
  for(const badTime of [Number.POSITIVE_INFINITY,Number.NEGATIVE_INFINITY,
   Number.MAX_SAFE_INTEGER+1,Number.MIN_SAFE_INTEGER-1,26*H+0.5]){
   const invalid=Object.defineProperties({}, {...Object.getOwnPropertyDescriptors(pending),
    time:{value:badTime,enumerable:true,configurable:true,writable:true},
   }) as Bar;
   assert.throws(()=>studyHourlyFvgMidpointAsOf([...bars,invalid],source,26*H),
    /Invalid|hourly|timestamp|candle/i);
   assert.equal(reads,0);
  }
  // Even a safe, hour-aligned opening can produce an unsafe close epoch.
  // Preflight must reject that future row before touching unrevealed fields.
  const lastAlignedSafeOpen=Math.floor((Number.MAX_SAFE_INTEGER-H)/H)*H;
  const unsafeCloseOpen=lastAlignedSafeOpen+H;
  assert.ok(Number.isSafeInteger(unsafeCloseOpen));
  assert.ok(!Number.isSafeInteger(unsafeCloseOpen+H));
  const unsafeClose=Object.defineProperties({}, {...Object.getOwnPropertyDescriptors(pending),
   time:{value:unsafeCloseOpen,enumerable:true,configurable:true,writable:true},
  }) as Bar;
  assert.throws(()=>studyHourlyFvgMidpointAsOf([...bars,unsafeClose],source,26*H),
   /Invalid|hourly|timestamp|candle/i);
  assert.equal(reads,0);
  // A malformed *second* pending hour must fail the entire archive before
  // reading the first pending hour's unrevealed market evidence. Ignoring
  // malformed trailing rows would make a source gap appear trustworthy.
  const invalidSecond=Object.defineProperties({}, {...Object.getOwnPropertyDescriptors(pending),
   time:{value:27*H+1,enumerable:true,configurable:true,writable:true},
  }) as Bar;
  assert.throws(()=>studyHourlyFvgMidpointAsOf([...bars,pending,invalidSecond],source,26*H),
   /Invalid|hourly|timestamp|candle/i);
  assert.equal(reads,0);
  // Duplicate future timestamps are ambiguous even when both candles are
  // unclosed. Reject the archive rather than silently choosing one row.
  const duplicateFuture=Object.defineProperties({}, {...Object.getOwnPropertyDescriptors(pending),
   time:{value:26*H,enumerable:true,configurable:true,writable:true},
  }) as Bar;
  assert.throws(()=>studyHourlyFvgMidpointAsOf([...bars,pending,duplicateFuture],source,26*H),
   /duplicate|strict|chronolog|timestamp|hourly|invalid/i);
  assert.equal(reads,0);
  // Two individually aligned future timestamps are still invalid if their
  // archive order reverses. Preflight must not inspect either unclosed row.
  const laterFuture=Object.defineProperties({}, {...Object.getOwnPropertyDescriptors(pending),
   time:{value:28*H,enumerable:true,configurable:true,writable:true},
  }) as Bar;
  const earlierFuture=Object.defineProperties({}, {...Object.getOwnPropertyDescriptors(pending),
   time:{value:27*H,enumerable:true,configurable:true,writable:true},
  }) as Bar;
  assert.throws(()=>studyHourlyFvgMidpointAsOf([...bars,laterFuture,earlierFuture],source,26*H),
   /strict|chronolog|timestamp|hourly|invalid|ascending/i);
  assert.equal(reads,0);
  // A future timestamp getter must not revise an already completed candle's
  // OHLC after the prefix has been copied. Descriptor revalidation catches
  // this mutation without ever reading the future candle's price fields.
  const mutableBars=bars.map(bar=>({...bar}));
  let futureTimeReads=0;
  const mutatingFuture=Object.defineProperties({}, {...Object.getOwnPropertyDescriptors(pending),
   time:{enumerable:true,configurable:true,get(){
    futureTimeReads++;
    mutableBars[23].close=mutableBars[23].close+1;
    return 26*H;
   }},
  }) as Bar;
  assert.throws(()=>studyHourlyFvgMidpointAsOf([...mutableBars,mutatingFuture],source,26*H),
   /changed|snapshot|candle|field|schema/i);
  assert.equal(futureTimeReads,1);
  assert.equal(reads,0);
  // The same snapshot protection must cover completed volume and minute
  // coverage, not just OHLC. A future timestamp getter cannot rewrite
  // earlier source evidence while the as-of scan is validating the archive.
  for(const field of ['volume','observed_minutes'] as const){
   const snapshotBars=bars.map(bar=>({...bar}));
   let timestampReads=0;
   const tamperingFuture=Object.defineProperties({}, {...Object.getOwnPropertyDescriptors(pending),
    time:{enumerable:true,configurable:true,get(){
     timestampReads++;
     snapshotBars[23][field]=(snapshotBars[23][field] ?? 0)+1;
     return 26*H;
    }},
   }) as Bar;
   assert.throws(()=>studyHourlyFvgMidpointAsOf([...snapshotBars,tamperingFuture],source,26*H),
    /changed|snapshot|candle|field|schema/i);
   assert.equal(timestampReads,1);
   assert.equal(reads,0);
  }
  // A future timestamp accessor cannot rewrite the time identity of an
  // already completed row. Otherwise a source gap could be relabelled as
  // continuous after the historical prefix was inspected.
  const retimedBars=bars.map(bar=>({...bar}));
  let retimeReads=0;
  const retimingFuture=Object.defineProperties({}, {...Object.getOwnPropertyDescriptors(pending),
   time:{enumerable:true,configurable:true,get(){
    retimeReads++;
    retimedBars[23].time=24*H;
    return 26*H;
   }},
  }) as Bar;
  assert.throws(()=>studyHourlyFvgMidpointAsOf([...retimedBars,retimingFuture],source,26*H),
   /changed|snapshot|candle|field|schema|chronolog/i);
  assert.equal(retimeReads,1);
  assert.equal(reads,0);
  // An unclosed row must not rewrite a completed candle's opening price
  // during timestamp preflight, even if its own OHLC is never consulted.
  const openingBars=bars.map(bar=>({...bar}));
  let openingReads=0;
  const openingFuture=Object.defineProperties({}, {...Object.getOwnPropertyDescriptors(pending),
   time:{enumerable:true,configurable:true,get(){
    openingReads++;
    openingBars[23].open+=1;
    return 26*H;
   }},
  }) as Bar;
  assert.throws(()=>studyHourlyFvgMidpointAsOf([...openingBars,openingFuture],source,26*H),
   /changed|snapshot|candle|field|schema|chronolog/i);
  assert.equal(openingReads,1);
  assert.equal(reads,0);
  // High/low are independent completed-bar evidence. A pending timestamp
  // accessor must not revise either extreme after the completed snapshot was
  // captured, even though its own unrevealed market fields remain untouched.
  for(const field of ['high','low'] as const){
   const extremeBars=bars.map(bar=>({...bar}));
   let timeReads=0;
   const extremeFuture=Object.defineProperties({}, {...Object.getOwnPropertyDescriptors(pending),
    time:{enumerable:true,configurable:true,get(){
     timeReads++;
     extremeBars[23][field]+=field==='high'?1:-1;
     return 26*H;
    }},
   }) as Bar;
   assert.throws(()=>studyHourlyFvgMidpointAsOf([...extremeBars,extremeFuture],source,26*H),
    /changed|snapshot|candle|field|schema|chronolog/i);
   assert.equal(timeReads,1);
   assert.equal(reads,0);
  }
  // A future timestamp accessor must not replace a completed source field
  // with a getter, even when that getter would return the original value.
  // A data-to-accessor change invalidates the captured evidence schema.
  const descriptorBars=bars.map(bar=>({...bar}));
  let descriptorTimeReads=0;
  let completedCloseReads=0;
  const originalClose=descriptorBars[23].close;
  const descriptorFuture=Object.defineProperties({}, {...Object.getOwnPropertyDescriptors(pending),
   time:{enumerable:true,configurable:true,get(){
    descriptorTimeReads++;
    Object.defineProperty(descriptorBars[23],'close',{
     enumerable:true,configurable:true,get(){completedCloseReads++;return originalClose;},
    });
    return 26*H;
   }},
  }) as Bar;
  assert.throws(()=>studyHourlyFvgMidpointAsOf([...descriptorBars,descriptorFuture],source,26*H),
   /changed|snapshot|candle|field|schema|accessor/i);
  assert.equal(descriptorTimeReads,1);
  assert.equal(completedCloseReads,0);
  assert.equal(reads,0);
  // Completed source-volume and coverage schema must also be immutable: a
  // future timestamp getter cannot substitute a lazy accessor for a plain
  // evidence value, even when the accessor would return that same value.
  for(const field of ['volume','observed_minutes'] as const){
   const evidenceBars=bars.map(bar=>({...bar}));
   const original=evidenceBars[23][field];
   let timestampReads=0;
   let evidenceGetterReads=0;
   const schemaFuture=Object.defineProperties({}, {...Object.getOwnPropertyDescriptors(pending),
    time:{enumerable:true,configurable:true,get(){
     timestampReads++;
     Object.defineProperty(evidenceBars[23],field,{
      enumerable:true,configurable:true,
      get(){evidenceGetterReads++;return original;},
     });
     return 26*H;
    }},
   }) as Bar;
   assert.throws(()=>studyHourlyFvgMidpointAsOf([...evidenceBars,schemaFuture],source,26*H),
    /changed|snapshot|candle|field|schema|accessor/i);
   assert.equal(timestampReads,1);
   assert.equal(evidenceGetterReads,0);
   assert.equal(reads,0);
  }
  // Removing a completed candle's evidence field during future timestamp
  // preflight must invalidate the captured prefix, not silently coerce an
  // absent price or coverage field into usable historical evidence.
  for(const field of ['close','volume','observed_minutes'] as const){
   const deletionBars=bars.map(bar=>({...bar}));
   let timeReads=0;
   const deletingFuture=Object.defineProperties({}, {...Object.getOwnPropertyDescriptors(pending),
    time:{enumerable:true,configurable:true,get(){
     timeReads++;
     Reflect.deleteProperty(deletionBars[23],field);
     return 26*H;
    }},
   }) as Bar;
   assert.throws(()=>studyHourlyFvgMidpointAsOf([...deletionBars,deletingFuture],source,26*H),
    /changed|snapshot|candle|field|schema|missing/i);
   assert.equal(timeReads,1);
   assert.equal(reads,0);
  }
  // A future timestamp accessor must not delete completed opening or extreme
  // prices. Missing OHLC evidence cannot be silently accepted as a valid
  // historical first-touch sequence; reject before future market-field reads.
  for(const field of ['open','high','low'] as const){
   const protectedBars=bars.map(bar=>({...bar}));
   let futureReads=0;
   const deletingFuture=Object.defineProperties({}, {...Object.getOwnPropertyDescriptors(pending),
    time:{enumerable:true,configurable:true,get(){
     futureReads++;
     Reflect.deleteProperty(protectedBars[23],field);
     return 26*H;
    }},
   }) as Bar;
   assert.throws(()=>studyHourlyFvgMidpointAsOf([...protectedBars,deletingFuture],source,26*H),
    /changed|snapshot|candle|field|schema|missing/i);
   assert.equal(futureReads,1);
   assert.equal(reads,0);
  }
  // Timestamp identity is evidence too: an unclosed row cannot replace a
  // completed hour's plain timestamp with a getter returning the same epoch.
  // The completed timestamp accessor must never execute during rejection.
  const timeSchemaBars=bars.map(bar=>({...bar}));
  let futureTimestampReads=0;
  let completedTimestampReads=0;
  const originalTime=timeSchemaBars[23].time;
  const timeSchemaFuture=Object.defineProperties({}, {...Object.getOwnPropertyDescriptors(pending),
   time:{enumerable:true,configurable:true,get(){
    futureTimestampReads++;
    Object.defineProperty(timeSchemaBars[23],'time',{
     enumerable:true,configurable:true,
     get(){completedTimestampReads++;return originalTime;},
    });
    return 26*H;
   }},
  }) as Bar;
  assert.throws(()=>studyHourlyFvgMidpointAsOf([...timeSchemaBars,timeSchemaFuture],source,26*H),
   /changed|snapshot|candle|field|schema|accessor/i);
  assert.equal(futureTimestampReads,1);
  assert.equal(completedTimestampReads,0);
  assert.equal(reads,0);
  // Completed OHLC opening/high/low fields must retain their plain-data
  // descriptors during future timestamp preflight, not merely their values.
  // This closes the descriptor substitution matrix beyond close/volume/time.
  for(const field of ['open','high','low'] as const){
   const protectedBars=bars.map(bar=>({...bar}));
   const original=protectedBars[23][field];
   let futureReads=0;
   let substitutedReads=0;
   const hostileFuture=Object.defineProperties({}, {...Object.getOwnPropertyDescriptors(pending),
    time:{enumerable:true,configurable:true,get(){
     futureReads++;
     Object.defineProperty(protectedBars[23],field,{
      enumerable:true,configurable:true,
      get(){substitutedReads++;return original;},
     });
     return 26*H;
    }},
   }) as Bar;
   assert.throws(()=>studyHourlyFvgMidpointAsOf([...protectedBars,hostileFuture],source,26*H),
    /changed|snapshot|candle|field|schema|accessor/i);
   assert.equal(futureReads,1);
   assert.equal(substitutedReads,0);
   assert.equal(reads,0);
  }
  // A future timestamp getter cannot change the descriptor flags of a
  // completed historical field while preserving its value. A frozen, non-configurable or
  // hidden field is not the same source schema as the captured plain row.
  for(const field of ['time','open','high','low','close','volume','observed_minutes'] as const){
   for(const changedFlag of ['enumerable','writable','configurable'] as const){
    const immutableBars=bars.map(bar=>({...bar}));
    let futureReads=0;
    const hostileFuture=Object.defineProperties({}, {...Object.getOwnPropertyDescriptors(pending),
     time:{enumerable:true,configurable:true,get(){
      futureReads++;
      Object.defineProperty(immutableBars[23],field,{[changedFlag]:false});
      return 26*H;
     }},
    }) as Bar;
    assert.throws(()=>studyHourlyFvgMidpointAsOf([...immutableBars,hostileFuture],source,26*H),
     /changed|snapshot|candle|field|schema|descriptor/i);
    assert.equal(futureReads,1);
    assert.equal(reads,0);
   }
  }
  const o=actual.observations.find(x=>x.direction===direction&&x.formationClosedAt===23*H);
  assert.ok(o);
  assert.equal(o.firstTouchOutcome,'INCOMPLETE_WINDOW');
  assert.equal(o.firstTouchCensorReason,'MISSING_HOUR');
  assert.equal(o.firstTouchCensorObservedAt,26*H);
  assert.equal(o.firstTouchObservedWaitBars,1);
  assert.equal(o.firstTouchClosedAt,null);
  assert.equal(o.volumeEvidenceReason,'NOT_EVALUATED');
  assert.equal(o.gates.verifiedVolume,'INSUFFICIENT_DATA');
  assert.equal(o.eligibleForLiveTrading,false);
  // A source *claim* of exchange volume cannot repair an unobserved wait
  // hour. It is not an independently authenticated exchange receipt.
  const claimedExchange={...source,volumeType:'exchange' as const,volumeVerified:true};
  const claimed=studyHourlyFvgMidpointAsOf(bars,claimedExchange,26*H);
  // Even caller-declared verified exchange volume must not expose an
  // unclosed future candle or change the completed-prefix observation.
  assert.deepEqual(studyHourlyFvgMidpointAsOf([...bars,pending,fartherPending],claimedExchange,26*H),claimed);
  assert.equal(reads,0);
  const claimedGap=claimed.observations.find(x=>x.direction===direction&&x.formationClosedAt===23*H);
  assert.ok(claimedGap);
  assert.equal(claimedGap.firstTouchOutcome,'INCOMPLETE_WINDOW');
  assert.equal(claimedGap.firstTouchCensorReason,'MISSING_HOUR');
  assert.equal(claimedGap.firstTouchObservedWaitBars,1);
  assert.equal(claimedGap.volumeEvidenceReason,'NOT_EVALUATED');
  assert.equal(claimedGap.gates.verifiedVolume,'INSUFFICIENT_DATA');
  assert.equal(claimedGap.eligibleForLiveTrading,false);
 });
}


for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending ${direction} timestamp cannot swap a completed archive slot after prefix capture`,()=>{
  const bull=direction==='BULLISH';
  const rows:Bar[]=Array.from({length:26},(_,i)=>({
   time:i*H,open:bull?100:101,high:bull?101:102,
   low:bull?99:100,close:bull?100:101,volume:10,observed_minutes:60,
  }));
  const original=studyHourlyFvgMidpointAsOf(rows,source,26*H);
  assert.ok(original);
  const hostileRows=rows.map(row=>({...row}));
  let futureTimeReads=0;
  let futureMarketReads=0;
  const forbidden=():number=>{futureMarketReads++;throw Error('future market field accessed');};
  const pending=({
   get time(){
    futureTimeReads++;
    // Replacing an indexed row can invalidate the captured completed prefix
    // even if the original row and its own field descriptors remain intact.
    hostileRows[23]={...hostileRows[23],close:hostileRows[23].close+1};
    return 26*H;
   },
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},
   get observed_minutes(){return forbidden();},
  }) as Bar;
  // A byte-for-byte-equivalent replacement is still a new archive row.
  // Reject it rather than relying solely on matching OHLC or descriptors.
  const identicalRows=rows.map(row=>({...row}));
  let identicalTimeReads=0;
  let identicalMarketReads=0;
  const identicalPending=({
   get time(){
    identicalTimeReads++;
    identicalRows[23]={...identicalRows[23]};
    return 26*H;
   },
   get open(){identicalMarketReads++;throw Error('future open accessed');},
   get high(){identicalMarketReads++;throw Error('future high accessed');},
   get low(){identicalMarketReads++;throw Error('future low accessed');},
   get close(){identicalMarketReads++;throw Error('future close accessed');},
   get volume(){identicalMarketReads++;throw Error('future volume accessed');},
   get observed_minutes(){identicalMarketReads++;throw Error('future coverage accessed');},
  }) as unknown as Bar;
  identicalRows.push(identicalPending);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(identicalRows,source,26*H),
   /changed|snapshot|archive|slot|candle|schema/i);
  assert.equal(identicalTimeReads,1);
  assert.equal(identicalMarketReads,0);
  // A future timestamp getter must not reorder two completed archive rows.
  // Even when their OHLC values are identical, their hourly identities and
  // chronological source positions are historical evidence, not future data.
  const reorderedRows=rows.map(row=>({...row}));
  let reorderTimeReads=0;
  let reorderMarketReads=0;
  const reorderedPending=({
   get time(){
    reorderTimeReads++;
    [reorderedRows[22],reorderedRows[23]]=[reorderedRows[23],reorderedRows[22]];
    return 26*H;
   },
   get open(){reorderMarketReads++;throw Error('future open accessed');},
   get high(){reorderMarketReads++;throw Error('future high accessed');},
   get low(){reorderMarketReads++;throw Error('future low accessed');},
   get close(){reorderMarketReads++;throw Error('future close accessed');},
   get volume(){reorderMarketReads++;throw Error('future volume accessed');},
   get observed_minutes(){reorderMarketReads++;throw Error('future coverage accessed');},
  }) as unknown as Bar;
  reorderedRows.push(reorderedPending);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(reorderedRows,source,26*H),
   /changed|snapshot|archive|slot|candle|schema|chronolog/i);
  assert.equal(reorderTimeReads,1);
  assert.equal(reorderMarketReads,0);
  hostileRows.push(pending);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(hostileRows,source,26*H),
   /changed|snapshot|archive|slot|candle|schema/i);
  assert.equal(futureTimeReads,1);
  assert.equal(futureMarketReads,0);
 });
}

for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending ${direction} timestamp cannot hide a completed archive index`,()=>{
  const bull=direction==='BULLISH';
  const rows:Bar[]=Array.from({length:26},(_,i)=>({
   time:i*H,open:bull?100:101,high:bull?101:102,
   low:bull?99:100,close:bull?100:101,volume:10,observed_minutes:60,
  }));
  let futureTimeReads=0;
  let futureMarketReads=0;
  const forbidden=():number=>{futureMarketReads++;throw Error('future market evidence accessed');};
  const pending=({
   get time(){
    futureTimeReads++;
    Object.defineProperty(rows,'23',{enumerable:false});
    return 26*H;
   },
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},get observed_minutes(){return forbidden();},
  }) as unknown as Bar;
  rows.push(pending);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(rows,source,26*H),
   /changed|snapshot|archive|slot|candle|schema|index|enumerable/i);
  assert.equal(futureTimeReads,1);
  assert.equal(futureMarketReads,0);
 });
}

for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending ${direction} timestamp cannot freeze a completed archive slot`,()=>{
  const bull=direction==='BULLISH';
  const rows:Bar[]=Array.from({length:26},(_,i)=>({
   time:i*H,open:bull?100:101,high:bull?101:102,
   low:bull?99:100,close:bull?100:101,volume:10,observed_minutes:60,
  }));
  let timestampReads=0;
  let futureMarketReads=0;
  const forbidden=():number=>{futureMarketReads++;throw Error('future evidence accessed');};
  const pending=({
   get time(){
    timestampReads++;
    // A completed row's slot descriptor is part of the captured archive.
    // Its value remains identical, but future data must not freeze the slot.
    Object.defineProperty(rows,'23',{writable:false});
    return 26*H;
   },
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},get observed_minutes(){return forbidden();},
  }) as unknown as Bar;
  rows.push(pending);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(rows,source,26*H),
   /changed|snapshot|archive|slot|candle|schema|descriptor|writable/i);
  assert.equal(timestampReads,1);
  assert.equal(futureMarketReads,0);
 });
}

for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending ${direction} timestamp cannot make a completed archive slot non-configurable`,()=>{
  const bull=direction==='BULLISH';
  const rows:Bar[]=Array.from({length:26},(_,i)=>({
   time:i*H,open:bull?100:101,high:bull?101:102,
   low:bull?99:100,close:bull?100:101,volume:10,observed_minutes:60,
  }));
  let timestampReads=0;
  let futureMarketReads=0;
  const forbidden=():number=>{futureMarketReads++;throw Error('future evidence accessed');};
  const pending=({
   get time(){
    timestampReads++;
    // A future timestamp must not permanently lock an already captured
    // completed index, even when its value and other flags are unchanged.
    Object.defineProperty(rows,'23',{configurable:false});
    return 26*H;
   },
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},get observed_minutes(){return forbidden();},
  }) as unknown as Bar;
  rows.push(pending);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(rows,source,26*H),
   /changed|snapshot|archive|slot|candle|schema|descriptor|configurable/i);
  assert.equal(timestampReads,1);
  assert.equal(futureMarketReads,0);
 });
}


for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending ${direction} timestamp cannot truncate completed hourly archive`,()=>{
  const bull=direction==='BULLISH';
  const rows:Bar[]=Array.from({length:26},(_,i)=>({
   time:i*H,open:bull?100:101,high:bull?101:102,
   low:bull?99:100,close:bull?100:101,volume:10,observed_minutes:60,
  }));
  let futureTimeReads=0;
  let futureMarketReads=0;
  const forbidden=():number=>{futureMarketReads++;throw Error('future market evidence accessed');};
  const pending=({
   get time(){
    futureTimeReads++;
    // A future timestamp getter cannot erase completed source history.
    rows.length=23;
    return 26*H;
   },
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},get observed_minutes(){return forbidden();},
  }) as unknown as Bar;
  rows.push(pending);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(rows,source,26*H),
   /changed|snapshot|archive|slot|candle|schema|length|missing/i);
  assert.equal(futureTimeReads,1);
  assert.equal(futureMarketReads,0);
 });
}

for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending ${direction} timestamp cannot delete a completed archive slot without shortening it`,()=>{
  const bull=direction==='BULLISH';
  const rows:Bar[]=Array.from({length:26},(_,i)=>({
   time:i*H,open:bull?100:101,high:bull?101:102,
   low:bull?99:100,close:bull?100:101,volume:10,observed_minutes:60,
  }));
  let timeReads=0;
  let futureMarketReads=0;
  const forbidden=():number=>{futureMarketReads++;throw Error('unclosed evidence accessed');};
  const pending=({
   get time(){
    timeReads++;
    // Unlike length truncation, delete leaves a sparse archive with the
    // original length; a missing completed slot cannot count as a no-touch.
    delete rows[23];
    return 26*H;
   },
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},get observed_minutes(){return forbidden();},
  }) as unknown as Bar;
  rows.push(pending);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(rows,source,26*H),
   /changed|snapshot|archive|slot|candle|schema|missing|hole/i);
  assert.equal(timeReads,1);
  assert.equal(futureMarketReads,0);
 });
}

for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending ${direction} timestamp cannot append a backdated completed hour during preflight`,()=>{
  const bull=direction==='BULLISH';
  const rows:Bar[]=Array.from({length:26},(_,i)=>({
   time:i*H,open:bull?100:101,high:bull?101:102,
   low:bull?99:100,close:bull?100:101,volume:10,observed_minutes:60,
  }));
  let timeReads=0;
  let futureMarketReads=0;
  const forbidden=():number=>{futureMarketReads++;throw Error('unclosed market field accessed');};
  const pending=({
   get time(){
    timeReads++;
    // The completed source prefix must not grow after its snapshot.
    // A backdated inserted observation is not evidence available as of capture.
    rows.push({...rows[23],time:23*H});
    return 26*H;
   },
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},get observed_minutes(){return forbidden();},
  }) as unknown as Bar;
  rows.push(pending);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(rows,source,26*H),
   /changed|snapshot|archive|slot|candle|schema|length|chronolog/i);
  assert.equal(timeReads,1);
  assert.equal(futureMarketReads,0);
 });
}

for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending ${direction} timestamp cannot splice a completed hour into captured history`,()=>{
  const bull=direction==='BULLISH';
  const rows:Bar[]=Array.from({length:26},(_,i)=>({
   time:i*H,open:bull?100:101,high:bull?101:102,
   low:bull?99:100,close:bull?100:101,volume:10,observed_minutes:60,
  }));
  let timeReads=0;
  let futureMarketReads=0;
  const forbidden=():number=>{futureMarketReads++;throw Error('future market evidence accessed');};
  const pending=({
   get time(){
    timeReads++;
    // Insertion shifts completed array indices, unlike a backdated append.
    // The captured prefix cannot be silently reindexed during preflight.
    rows.splice(23,0,{...rows[23]});
    return 26*H;
   },
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},get observed_minutes(){return forbidden();},
  }) as unknown as Bar;
  rows.push(pending);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(rows,source,26*H),
   /changed|snapshot|archive|slot|candle|schema|length|chronolog/i);
  assert.equal(timeReads,1);
  assert.equal(futureMarketReads,0);
 });
}


for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending ${direction} timestamp cannot reverse captured completed-hour chronology`,()=>{
  const bull=direction==='BULLISH';
  const rows:Bar[]=Array.from({length:26},(_,i)=>({
   time:i*H,open:bull?100:101,high:bull?101:102,
   low:bull?99:100,close:bull?100:101,volume:10,observed_minutes:60,
  }));
  let timeReads=0;
  let futureMarketReads=0;
  const forbidden=():number=>{futureMarketReads++;throw Error('future market evidence accessed');};
  const pending=({
   get time(){
    timeReads++;
    // A pending timestamp cannot reorder the completed historical prefix.
    rows.reverse();
    return 26*H;
   },
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},get observed_minutes(){return forbidden();},
  }) as unknown as Bar;
  rows.push(pending);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(rows,source,26*H),
   /changed|snapshot|archive|slot|candle|schema|chronolog|order/i);
  assert.equal(timeReads,1);
  assert.equal(futureMarketReads,0);
 });
}

for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending ${direction} timestamp cannot revise completed-hour volume in place`,()=>{
  const bull=direction==='BULLISH';
  const rows:Bar[]=Array.from({length:26},(_,i)=>({
   time:i*H,open:bull?100:101,high:bull?101:102,
   low:bull?99:100,close:bull?100:101,volume:10,observed_minutes:60,
  }));
  let timeReads=0;
  let futureMarketReads=0;
  const forbidden=():number=>{futureMarketReads++;throw Error('unclosed market evidence accessed');};
  const pending=({
   get time(){
    timeReads++;
    // A later timestamp accessor must not retroactively rewrite the
    // completed archive's measured volume, even when time/order is intact.
    rows[23].volume=1000;
    return 26*H;
   },
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},get observed_minutes(){return forbidden();},
  }) as unknown as Bar;
  rows.push(pending);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(rows,source,26*H),
   /changed|snapshot|archive|candle|volume|evidence/i);
  assert.equal(timeReads,1);
  assert.equal(futureMarketReads,0);
 });
}

for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending ${direction} timestamp cannot revise completed-hour close in place`,()=>{
  const bull=direction==='BULLISH';
  const rows:Bar[]=Array.from({length:26},(_,i)=>({
   time:i*H,open:bull?100:101,high:bull?101:102,
   low:bull?99:100,close:bull?100:101,volume:10,observed_minutes:60,
  }));
  let timeReads=0;
  let futureMarketReads=0;
  const forbidden=():number=>{futureMarketReads++;throw Error('unclosed market evidence accessed');};
  const pending=({
   get time(){
    timeReads++;
    // A pending timestamp cannot retroactively alter a closed candle's
    // close, which can change the historical FVG and rejection decision.
    rows[23].close=bull?100.5:101.5;
    return 26*H;
   },
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},get observed_minutes(){return forbidden();},
  }) as unknown as Bar;
  rows.push(pending);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(rows,source,26*H),
   /changed|snapshot|archive|candle|close|evidence/i);
  assert.equal(timeReads,1);
  assert.equal(futureMarketReads,0);
 });
}

for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending ${direction} timestamp cannot revise completed-hour wick extremes in place`,()=>{
  const bull=direction==='BULLISH';
  for(const field of ['high','low'] as const){
   const rows:Bar[]=Array.from({length:26},(_,i)=>({
    time:i*H,open:bull?100:101,high:bull?101:102,
    low:bull?99:100,close:bull?100:101,volume:10,observed_minutes:60,
   }));
   let timeReads=0;
   let futureMarketReads=0;
   const forbidden=():number=>{futureMarketReads++;throw Error('unclosed market evidence accessed');};
   const pending=({
    get time(){
     timeReads++;
     // A pending timestamp must not rewrite a completed wick: a revised
     // high/low can change whether the historical midpoint was touched.
     rows[23][field]=field==='high'?(bull?102:103):(bull?98:99);
     return 26*H;
    },
    get open(){return forbidden();},get high(){return forbidden();},
    get low(){return forbidden();},get close(){return forbidden();},
    get volume(){return forbidden();},get observed_minutes(){return forbidden();},
   }) as unknown as Bar;
   rows.push(pending);
   assert.throws(()=>studyHourlyFvgMidpointAsOf(rows,source,26*H),
    /changed|snapshot|archive|candle|evidence|high|low/i);
   assert.equal(timeReads,1);
   assert.equal(futureMarketReads,0);
  }
 });
}

for(const direction of ['BULLISH','BEARISH'] as const){
 test(`pending ${direction} timestamp cannot revise completed-hour minute coverage in place`,()=>{
  const bull=direction==='BULLISH';
  const rows:Bar[]=Array.from({length:26},(_,i)=>({
   time:i*H,open:bull?100:101,high:bull?101:102,
   low:bull?99:100,close:bull?100:101,volume:10,observed_minutes:60,
  }));
  let timeReads=0;
  let futureMarketReads=0;
  const forbidden=():number=>{futureMarketReads++;throw Error('unclosed market evidence accessed');};
  const pending=({
   get time(){
    timeReads++;
    // A closed hour cannot lose observed-minute evidence when a future
    // timestamp is inspected. Price and volume are intentionally unchanged.
    rows[23].observed_minutes=59;
    return 26*H;
   },
   get open(){return forbidden();},get high(){return forbidden();},
   get low(){return forbidden();},get close(){return forbidden();},
   get volume(){return forbidden();},get observed_minutes(){return forbidden();},
  }) as unknown as Bar;
  rows.push(pending);
  assert.throws(()=>studyHourlyFvgMidpointAsOf(rows,source,26*H),
   /changed|snapshot|archive|candle|coverage|evidence/i);
  assert.equal(timeReads,1);
  assert.equal(futureMarketReads,0);
 });
}
