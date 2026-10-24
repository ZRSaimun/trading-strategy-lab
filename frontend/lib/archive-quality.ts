/** Data-quality diagnostics for a *loaded* read-only historical archive window.
 * Nothing here asserts whether apparent gaps are missing data or market closures.
 * Calendar/session and actual bid/ask entitlement checks remain separate work.
 */
export type HistoricalCandle={
 time:number;open:number;high:number;low:number;close:number;
 volume:number|null;observed_minutes:number;
};
export type ArchiveQualitySummary={
 bars:number;firstTime:number|null;lastTime:number|null;
 invalidBars:number;unobservedSpans:number;unobservedBuckets:number|null;
 partialBuckets:number|null;fullBuckets:number|null;minutesObserved:number;
 unknownVolumeBars:number;zeroVolumeBars:number;bucketDurationSeconds:number|null;
};
const FRAME_SECONDS:Record<string,number>={
 '1m':60,'3m':180,'5m':300,'15m':900,'30m':1800,
 '1H':3600,'2H':7200,'4H':14400,'1D':86400,'1W':604800
};
const INTRADAY=new Set(['1m','3m','5m','15m','30m','1H','2H','4H']);

export function summarizeHistoricalQuality(
 bars:ReadonlyArray<HistoricalCandle>,timeframe:string
):ArchiveQualitySummary{
 if(!(timeframe in FRAME_SECONDS)&&timeframe!=='1M')
  throw Error('Unrecognized historical timeframe');
 const seconds=FRAME_SECONDS[timeframe]??null;
 const expected=seconds!==null&&INTRADAY.has(timeframe)?seconds/60:null;
 let invalidBars=0,unobservedSpans=0,unobservedBuckets:number|null=seconds===null?null:0;
 let partialBuckets:number|null=expected===null?null:0,fullBuckets:number|null=expected===null?null:0;
 let unknownVolumeBars=0,zeroVolumeBars=0,minutesObserved=0;
 for(let i=0;i<bars.length;i++){
  const b=bars[i],prev=bars[i-1];
  if(!Number.isSafeInteger(b.time)||b.time<0||
     ![b.open,b.high,b.low,b.close,b.observed_minutes].every(Number.isFinite)||
     !Number.isInteger(b.observed_minutes)||b.observed_minutes<1||
     b.low>Math.min(b.open,b.close)||b.high<Math.max(b.open,b.close)||
     b.low>b.high||b.volume!==null&&(!Number.isFinite(b.volume)||b.volume<0)||
     (prev!==undefined&&b.time<=prev.time)||
     (expected!==null&&b.observed_minutes>expected)||
     (seconds!==null&&timeframe!=='1W'&&b.time%seconds!==0)||
     (timeframe==='1W'&&(b.time-345600)%604800!==0)||
     (timeframe==='1M'&&Number.isSafeInteger(b.time)&&
      (()=>{
       const d=new Date(b.time*1000);
       return d.getUTCDate()!==1||d.getUTCHours()!==0||d.getUTCMinutes()!==0||d.getUTCSeconds()!==0;
      })()))
   invalidBars++;
  minutesObserved+=Number.isFinite(b.observed_minutes)&&b.observed_minutes>0?b.observed_minutes:0;
  if(b.volume===null)unknownVolumeBars++;
  else if(b.volume===0)zeroVolumeBars++;
  if(expected!==null){
   if(b.observed_minutes===expected)fullBuckets=(fullBuckets??0)+1;
   else partialBuckets=(partialBuckets??0)+1;
  }
  if(prev!==undefined&&seconds!==null&&b.time>prev.time+seconds){
   unobservedSpans++;
   // Count missing timeframe positions without assuming missing *market* data.
   unobservedBuckets=(unobservedBuckets??0)+Math.max(0,Math.floor((b.time-prev.time)/seconds)-1);
  }
 }
 return {bars:bars.length,firstTime:bars[0]?.time??null,
  lastTime:bars.at(-1)?.time??null,invalidBars,
  unobservedSpans,unobservedBuckets,partialBuckets,fullBuckets,
  minutesObserved,unknownVolumeBars,zeroVolumeBars,bucketDurationSeconds:seconds};
}
