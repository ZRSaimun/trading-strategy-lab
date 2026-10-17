import {analyze,FRAMES,type Bar} from './research.ts';
export const ALERT_KINDS=['CLOSE ABOVE','CLOSE BELOW','SELL-SIDE SWEEP','BUY-SIDE SWEEP','BULLISH FVG','BEARISH FVG'] as const;
export type AlertKind=typeof ALERT_KINDS[number];
export type AlertRule={id:string;title:string;created_at:number;payload:{instrument:string;timeframe:string;kind:AlertKind;level:number;acceptance:number;enabled:boolean;version:number}};
export type AlertEvent={id:string;title:string;created_at:number;payload:{ruleId:string;ruleVersion:number;instrument:string;timeframe:string;kind:AlertKind;state:'WATCHING LEVEL'|'SWEEP DETECTED'|'PATTERN OBSERVED';mode:'HISTORICAL REPLAY';source:string;datasetHash:string;observedAt:number;lastBarOpen:number;lastBarClose:number;quoteTimestamp:null;live:false;level:number;evidence:number[];message:string;cancellation:string;execution:'NONE';news:'NOT CONNECTED'}};
export function validateRule(rule:AlertRule){
 const p=rule.payload;
 if(!/^[a-zA-Z0-9-]{1,40}$/.test(rule.id)||!rule.title.trim()||rule.title.length>160||!['XAUUSD-IMPORT','NDX-IMPORT'].includes(p.instrument)||!['1m','3m','5m','15m','30m','1H','2H','4H','1D'].includes(p.timeframe)||!ALERT_KINDS.includes(p.kind)||!Number.isFinite(p.level)||!Number.isInteger(p.acceptance)||p.acceptance<1||p.acceptance>10||!Number.isInteger(p.version)||p.version<1||p.version>1000000||typeof p.enabled!=='boolean')throw Error('Invalid alert rule');
}
export function evaluateAlert(rule:AlertRule,bars:Bar[],context:{instrument:string;timeframe:string;source:string;datasetHash:string},seen:ReadonlySet<string>=new Set()):AlertEvent|null{
 validateRule(rule);const p=rule.payload;
 if(!p.enabled||p.instrument!==context.instrument||p.timeframe!==context.timeframe||bars.length<2||!/^[a-f0-9]{64}$/.test(context.datasetHash)||!context.source)return null;
 const b=bars.at(-1)!,seconds=FRAMES[p.timeframe];
 // Partial aggregates, missing minutes and non-contiguous evidence cannot confirm an event.
 const count=p.kind.startsWith('CLOSE')?p.acceptance+1:Math.min(bars.length,6);
 const recent=bars.slice(-count);
 if(recent.some((x,i)=>x.observed_minutes!==seconds/60||(i>0&&x.time-recent[i-1].time!==seconds)))return null;
 const id=`${rule.id}-v${p.version}-${context.datasetHash}-${b.time}`;if(seen.has(id))return null;
 let matched=false,evidence:number[]=[],level=p.level,state:AlertEvent['payload']['state']='PATTERN OBSERVED';
 if(p.kind==='CLOSE ABOVE'||p.kind==='CLOSE BELOW'){
  if(bars.length<p.acceptance+1)return null;
  const previous=bars[bars.length-p.acceptance-1],accepted=bars.slice(-p.acceptance),up=p.kind==='CLOSE ABOVE';
  matched=up?previous.close<=p.level&&accepted.every(x=>x.close>p.level):previous.close>=p.level&&accepted.every(x=>x.close<p.level);
  evidence=[previous.time,...accepted.map(x=>x.time)];state='WATCHING LEVEL';
 }else{
  let start=bars.length-1;while(start>0&&bars[start-1].observed_minutes===seconds/60&&bars[start].time-bars[start-1].time===seconds)start--;
  const detection=analyze(bars.slice(start),2,p.timeframe).find(d=>d.kind===p.kind&&d.observed_at===b.time+seconds);
  if(detection){matched=true;evidence=detection.reference_times;level=detection.level;state=p.kind.includes('SWEEP')?'SWEEP DETECTED':'PATTERN OBSERVED'}
 }
 if(!matched)return null;
 return {id,title:`Historical · ${rule.title}`,created_at:Math.floor(Date.now()/1000),payload:{ruleId:rule.id,ruleVersion:p.version,instrument:p.instrument,timeframe:p.timeframe,kind:p.kind,state,mode:'HISTORICAL REPLAY',source:context.source,datasetHash:context.datasetHash,observedAt:b.time+seconds,lastBarOpen:b.time,lastBarClose:b.close,quoteTimestamp:null,live:false,level,evidence,message:p.kind.startsWith('CLOSE')?`${p.acceptance} completed candle(s) accepted across a level. WAIT: this is not a BUY or SELL confirmation.`:'Completed-bar pattern observed. WAIT: displacement, higher-timeframe alignment, defended retest, costs and opposing liquidity are not all validated.',cancellation:'Research observation only. Reclaim, invalidation, missing data or later opposing evidence require reassessment; no demo order exists.',execution:'NONE',news:'NOT CONNECTED'}};
}

export function evaluateAdvance(rules:AlertRule[],bars:Bar[],fromCount:number,toCount:number,context:Parameters<typeof evaluateAlert>[2],seen:ReadonlySet<string>):AlertEvent[]{
 if(fromCount<1||toCount<=fromCount)return [];
 const ids=new Set(seen),out:AlertEvent[]=[];
 for(let count=fromCount+1;count<=Math.min(toCount,bars.length);count++){
  const prefix=bars.slice(0,count);
  for(const rule of rules){const event=evaluateAlert(rule,prefix,context,ids);if(event){ids.add(event.id);out.push(event)}}
 }
 return out;
}
