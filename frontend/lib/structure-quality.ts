/**
 * Causal quality gate for structural observations. Each eligible bar belongs to
 * a run of complete, consecutive UTC candles; -1 marks an unusable candle.
 * Runs reset on partial bars, malformed OHLC, duplicates, backwards time and
 * any unknown gap. This intentionally rejects patterns across market closures:
 * no exchange calendar or source provenance is available to prove continuity.
 */
const SECONDS:Record<string,number>={'1m':60,'3m':180,'5m':300,'15m':900,'30m':1800,'1H':3600,'2H':7200,'4H':14400,'1D':86400,'1W':604800,'1M':0};
export type QualityBar={time:number;open:number;high:number;low:number;close:number;observed_minutes:number};
function monthOrdinal(time:number){const d=new Date(time*1000);return d.getUTCFullYear()*12+d.getUTCMonth()}
function aligned(time:number,frame:string){
 if(frame==='1M'){
  const d=new Date(time*1000);
  return d.getUTCDate()===1&&d.getUTCHours()===0&&d.getUTCMinutes()===0&&d.getUTCSeconds()===0;
 }
 if(frame==='1W')return (time-345600)%604800===0; // Monday 00:00 UTC
 return time%SECONDS[frame]===0;
}
function consecutive(previous:number,current:number,frame:string){
 if(frame==='1M')return monthOrdinal(current)===monthOrdinal(previous)+1;
 return current-previous===SECONDS[frame];
}
export function validStructureSegments(bars:readonly QualityBar[],frame:string):number[]{
 if(!Object.prototype.hasOwnProperty.call(SECONDS,frame))throw Error('Unsupported structure timeframe');
 const starts:number[]=[];
 let start=0,previous:number|null=null;
 for(let i=0;i<bars.length;i++){
  const b=bars[i],seconds=SECONDS[frame];
  const valid=Number.isSafeInteger(b.time)&&b.time>=0&&b.time<=8_640_000_000&&aligned(b.time,frame)&&
    [b.open,b.high,b.low,b.close].every(Number.isFinite)&&
    b.low<=Math.min(b.open,b.close)&&b.high>=Math.max(b.open,b.close)&&b.low<=b.high&&
    Number.isSafeInteger(b.observed_minutes)&&b.observed_minutes>0&&
    (seconds>0&&seconds<=14400?b.observed_minutes===seconds/60:true);
  if(!valid){starts.push(-1);previous=null;continue}
  if(previous===null||!consecutive(previous,b.time,frame))start=i;
  starts.push(start);
  previous=b.time;
 }
 return starts;
}
