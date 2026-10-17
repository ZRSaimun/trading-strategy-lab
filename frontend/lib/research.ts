export type Bar={time:number;open:number;high:number;low:number;close:number;volume:number|null;observed_minutes:number};
export const FRAMES:Record<string,number>={'1m':60,'3m':180,'5m':300,'15m':900,'30m':1800,'1H':3600,'2H':7200,'4H':14400,'1D':86400,'1W':604800,'1M':0};
// Small strict RFC4180 parser: rejects malformed quotes instead of guessing columns.
export function csvRows(text:string):string[][]{
 const rows:string[][]=[];let row:string[]=[],field='',quoted=false,closed=false;
 const finish=()=>{row.push(field);field='';closed=false};
 for(let i=0;i<text.length;i++){
  const c=text[i];
  if(quoted){if(c==='"'){if(text[i+1]==='"'){field+='"';i++}else{quoted=false;closed=true}}else field+=c;continue}
  if(c==='"'){if(field||closed)throw Error('Malformed CSV quote');quoted=true}
  else if(c===',')finish();
  else if(c==='\n'||c==='\r'){if(c==='\r'&&text[i+1]==='\n')i++;finish();if(row.some(x=>x!==''))rows.push(row);row=[]}
  else{if(closed)throw Error('Unexpected text after closing quote');field+=c}
 }
 if(quoted)throw Error('Unclosed CSV quote');
 if(field||row.length||closed){finish();rows.push(row)}return rows;
}
export function parseCSV(text:string):Bar[]{
 const [headers,...rows]=csvRows(text.replace(/^\uFEFF/,''));
 if(!headers||!['time','open','high','low','close'].every(x=>headers.includes(x)))throw Error('Required headers: time,open,high,low,close');
 if(new Set(headers).size!==headers.length)throw Error('Duplicate headers');
 if(!rows.length||rows.length>100000)throw Error('Import requires 1–100,000 one-minute candles');
 let prior=-Infinity;
 return rows.map((r,index)=>{
  const fail=(msg:string):never=>{throw Error(`Row ${index+2}: ${msg}`)};
  if(r.length!==headers.length)fail('Column count mismatch');
  const raw=Object.fromEntries(headers.map((h,i)=>[h,r[i]]));
  if(!/^\d{4}-\d\d-\d\dT\d\d:\d\d(?::00(?:\.0+)?)?(?:Z|[+-]\d\d:\d\d)$/.test(raw.time))fail('Minute-aligned ISO time with explicit timezone required');
  const time=Date.parse(raw.time)/1000;
  if(!Number.isFinite(time)||time%60!==0||time<=prior)fail('Invalid, duplicate or unordered timestamp');
  prior=time;
  const n=(key:string)=>raw[key]?.trim()?Number(raw[key]):NaN;
  const [open,high,low,close]=['open','high','low','close'].map(n);
  if(![open,high,low,close].every(Number.isFinite)||low>Math.min(open,close)||high<Math.max(open,close)||low>high)fail('Invalid OHLC');
  const volume=raw.volume?.trim()?Number(raw.volume):null;
  if(volume!==null&&(!Number.isFinite(volume)||volume<0))fail('Invalid volume');
  return {time,open,high,low,close,volume,observed_minutes:1};
 });
}
export function aggregate(rows:Bar[],frame:string):Bar[]{
 if(!(frame in FRAMES))throw Error('Unsupported timeframe');
 const buckets=new Map<number,Bar>();
 for(const r of rows){
  const date=new Date(r.time*1000);
  const t=frame==='1M'?Date.UTC(date.getUTCFullYear(),date.getUTCMonth(),1)/1000:frame==='1W'?Math.floor((r.time-345600)/604800)*604800+345600:Math.floor(r.time/FRAMES[frame])*FRAMES[frame];
  const b=buckets.get(t);
  if(!b)buckets.set(t,{...r,time:t});
  else{b.high=Math.max(b.high,r.high);b.low=Math.min(b.low,r.low);b.close=r.close;b.volume=b.volume!==null&&r.volume!==null?b.volume+r.volume:null;b.observed_minutes+=r.observed_minutes}
 }
 return [...buckets.values()];
}
export type Detection={kind:string;direction:string;observed_at:number;reference_times:number[];level:number;explanation:string;rule_version:string};
export function analyze(bars:Bar[],swing=2,frame='1m'):Detection[]{
 // Caller passes completed bars only. A swing is usable only after `swing` right bars close.
 const out:Detection[]=[];let high:{value:number;time:number;broken:boolean}|null=null,low:{value:number;time:number;broken:boolean}|null=null;
 for(let i=0;i<bars.length;i++){
  const b=bars[i],p=bars[i-1],j=i-swing;
  const date=new Date(b.time*1000);
  const closedAt=frame==='1M'?Date.UTC(date.getUTCFullYear(),date.getUTCMonth()+1,1)/1000:b.time+(FRAMES[frame]||60);
  if(j>=swing){const candidate=bars[j],window=bars.slice(j-swing,j+swing+1);
   if(window.every((x,k)=>k===swing||x.high<candidate.high))high={value:candidate.high,time:candidate.time,broken:false};
   if(window.every((x,k)=>k===swing||x.low>candidate.low))low={value:candidate.low,time:candidate.time,broken:false};
  }
  const emit=(kind:string,direction:string,level:number,times:number[],explanation:string)=>out.push({kind,direction,level,observed_at:closedAt,reference_times:times,explanation,rule_version:'structure-research-v1'});
  if(low&&!low.broken&&b.low<low.value&&b.close>low.value)emit('SELL-SIDE SWEEP','bullish observation',low.value,[low.time,b.time],'Wick below confirmed swing low; same candle closes back above. WAIT: displacement and defended retest not confirmed.');
  if(high&&!high.broken&&b.high>high.value&&b.close<high.value)emit('BUY-SIDE SWEEP','bearish observation',high.value,[high.time,b.time],'Wick above confirmed swing high; same candle closes back below. WAIT: displacement and defended retest not confirmed.');
  if(high&&!high.broken&&p&&p.close<=high.value&&b.close>high.value){emit('BULLISH STRUCTURE BREAK','bullish observation',high.value,[high.time,b.time],'Close above a confirmed swing high. Contextual MSS/CHOCH and retest are not inferred.');high.broken=true}
  if(low&&!low.broken&&p&&p.close>=low.value&&b.close<low.value){emit('BEARISH STRUCTURE BREAK','bearish observation',low.value,[low.time,b.time],'Close below a confirmed swing low. First break is not a SELL signal.');low.broken=true}
  if(i>=2){const a=bars[i-2];if(a.high<b.low)emit('BULLISH FVG','bullish observation',a.high,[a.time,bars[i-1].time,b.time],`Three-candle wick gap ${a.high}–${b.low}. Formation only; mitigation not evaluated.`);if(a.low>b.high)emit('BEARISH FVG','bearish observation',a.low,[a.time,bars[i-1].time,b.time],`Three-candle wick gap ${b.high}–${a.low}. Formation only; mitigation not evaluated.`)}
 }
 return out;
}
export function replayPrefix(bars:Bar[],count:number){return bars.slice(0,Math.max(0,Math.min(bars.length,Math.floor(count))))}
