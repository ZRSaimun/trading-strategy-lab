import {validateRule,ALERT_KINDS} from './alerts.ts';
import {parseCSV} from './research.ts';
export type WorkspaceEntry={key:string;value:unknown};
export const BACKUP_LIMIT=64000000;
const keys=new Set(['watchlist','audit','dataset:XAUUSD-IMPORT','dataset:NDX-IMPORT','drawings:XAUUSD-IMPORT','drawings:NDX-IMPORT','research:backtests','research:journal','research:alert-rules','research:alert-events']);
const object=(v:unknown):v is Record<string,any>=>v!==null&&typeof v==='object'&&!Array.isArray(v);
function fail():never{throw Error('Invalid workspace backup; no data was changed')}
export function validateEntries(input:unknown):WorkspaceEntry[]{
 if(!Array.isArray(input)||input.length>keys.size)fail();
 const seen=new Set<string>();
 for(const entry of input){
  if(!object(entry)||!keys.has(entry.key)||seen.has(entry.key))fail();seen.add(entry.key);
  const value=entry.value;
  if(entry.key==='watchlist'){
   if(!Array.isArray(value)||value.length>2||new Set(value).size!==value.length||value.some(x=>!['XAUUSD-IMPORT','NDX-IMPORT'].includes(x)))fail();
  }else if(entry.key.startsWith('dataset:')){
   if(!object(value)||!Array.isArray(value.rows)||value.rows.length<1||value.rows.length>100000||!object(value.meta))fail();
   const m=value.meta;
   if(typeof m.source!=='string'||!m.source.trim()||m.source.length>160||!['none','tick','exchange'].includes(m.volume_type)||!/^[0-9a-f]{64}$/.test(m.sha256)||!Number.isFinite(m.retrieved_at))fail();
   // Reuse the import validator instead of trusting saved timestamps or price coordinates.
   const csv=['time,open,high,low,close,volume',...value.rows.map((r:unknown)=>{
    if(!object(r)||!Number.isSafeInteger(r.time)||r.observed_minutes!==1||!['open','high','low','close'].every(k=>typeof r[k]==='number'&&Number.isFinite(r[k]))||(r.volume!==null&&(typeof r.volume!=='number'||!Number.isFinite(r.volume))))fail();
    return [new Date(r.time*1000).toISOString(),r.open,r.high,r.low,r.close,r.volume??''].join(',');
   })].join('\n');
   const rows=parseCSV(csv),gaps=rows.slice(1).filter((r,n)=>r.time-rows[n].time>60).length;
   if(m.rows!==rows.length||m.start!==rows[0].time||m.end!==rows.at(-1)!.time||m.gaps!==gaps||(m.volume_type==='none'&&rows.some(r=>r.volume!==null)))fail();
  }else if(entry.key.startsWith('drawings:')){
   if(!Array.isArray(value)||value.length>10000)fail();const ids=new Set();
   for(const d of value){
    if(!object(d)||typeof d.id!=='string'||d.id.length>128||ids.has(d.id)||!['horizontal','trendline','rectangle','note'].includes(d.kind)||!Number.isSafeInteger(d.version)||d.version<1||typeof d.text!=='string'||d.text.length>10000||!Array.isArray(d.points)||d.points.length!==(['trendline','rectangle'].includes(d.kind)?2:1)||d.points.some((p:unknown)=>!object(p)||!Number.isSafeInteger(p.time)||!Number.isFinite(p.price)))fail();ids.add(d.id);
   }
  }else if(entry.key==='audit'){
   if(!Array.isArray(value)||value.length>200||value.some(r=>!object(r)||typeof r.action!=='string'||!Number.isFinite(r.time)))fail();
  }else{
   const cap=entry.key==='research:backtests'?20:entry.key==='research:alert-rules'?100:500;
   if(!Array.isArray(value)||value.length>cap)fail();const ids=new Set();
   for(const r of value){if(!object(r)||typeof r.id!=='string'||!/^[a-zA-Z0-9-]{1,128}$/.test(r.id)||ids.has(r.id)||typeof r.title!=='string'||r.title.length>200||!object(r.payload)||JSON.stringify(r).length>6000000)fail();validateResearch(entry.key,r);ids.add(r.id)}
  }
 }
 return input;
}

function validateResearch(key:string,r:Record<string,any>){
 const p=r.payload;
 const instrument=()=>{if(!['XAUUSD-IMPORT','NDX-IMPORT'].includes(p.instrument))fail()};
 if(!Number.isFinite(r.created_at)||!Number.isFinite(new Date(r.created_at*1000).getTime()))fail();
 if(key==='research:alert-rules'){validateRule(r as any);instrument()}
 if(key==='research:alert-events'){
  instrument();if(!ALERT_KINDS.includes(p.kind)||!['WATCHING LEVEL','SWEEP DETECTED','PATTERN OBSERVED'].includes(p.state)||p.mode!=='HISTORICAL REPLAY'||p.live!==false||p.execution!=='NONE'||!Number.isFinite(p.observedAt)||!Number.isFinite(new Date(p.observedAt*1000).getTime())||!Number.isFinite(p.level)||!Array.isArray(p.evidence)||p.evidence.some((n:unknown)=>!Number.isFinite(n))||!['source','message','timeframe'].every(k=>typeof p[k]==='string'))fail();
 }
 if(key==='research:journal'){
  instrument();const t=p.trade;
  if(typeof p.notes!=='string'||p.notes.length>5000||!['SIMULATED ONLY','USER-REPORTED DEMO ENTRY'].includes(p.entryStatus)||typeof p.runId!=='string'||!object(t)||!['entryAt','exitAt','pnl','r'].every(k=>Number.isFinite(t[k]))||!['reason','verification'].every(k=>typeof t[k]==='string')||!Number.isFinite(new Date(t.entryAt*1000).getTime()))fail();
 }
 if(key==='research:backtests'){
  instrument();if(!object(p.window)||!['start','end','bars'].every(k=>Number.isFinite(p.window[k]))||!['source','datasetHash','notes'].every(k=>typeof p[k]==='string')||!Array.isArray(p.reports)||p.reports.length>5||!Array.isArray(p.splits)||p.splits.length>3)fail();
  const report=(r:unknown)=>{if(!object(r)||!object(r.metrics)||!Array.isArray(r.trades)||!Array.isArray(r.warnings)||!object(r.config)||!object(r.rejections)||!Array.isArray(r.equity)||!Number.isFinite(r.config.capital)||!['A','B','C','D','E'].includes(r.strategy)||typeof r.ruleVersion!=='string'||!Number.isFinite(r.start)||!Number.isFinite(r.end)||r.warnings.some((w:unknown)=>typeof w!=='string')||r.equity.some((e:unknown)=>!object(e)||!['time','mark','balance'].every(k=>Number.isFinite(e[k]))))fail();for(const t of r.trades){if(!object(t)||!['entryAt','entry','stop','target','pnl','costs','r'].every(k=>Number.isFinite(t[k]))||!Number.isFinite(new Date(t.entryAt*1000).getTime())||typeof t.reason!=='string'||typeof t.id!=='string'||!['BUY','SELL'].includes(t.direction))fail()}if(r.metrics.wilson95!==null&&(!Array.isArray(r.metrics.wilson95)||r.metrics.wilson95.length!==2||r.metrics.wilson95.some((v:unknown)=>!Number.isFinite(v))))fail();for(const k of ['trades','avgWin','avgLoss','expectancy','averageR','netPnl','netReturn','maxDrawdown','maxDrawdownPercent','rejected'])if(!Number.isFinite(r.metrics[k]))fail();for(const k of ['winRate','profitFactor'])if(r.metrics[k]!==null&&!Number.isFinite(r.metrics[k]))fail()};
  p.reports.forEach(report);for(const split of p.splits){if(!object(split)||typeof split.name!=='string'||!Array.isArray(split.reports)||split.reports.length>5)fail();split.reports.forEach(report)}
 }
}

async function digest(entries:WorkspaceEntry[]){const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(entries)));return Array.from(new Uint8Array(bytes),x=>x.toString(16).padStart(2,'0')).join('')}
export async function encodeBackup(entries:WorkspaceEntry[]){
 validateEntries(entries);const result={format:'trading-strategy-lab-workspace',version:1,createdAt:new Date().toISOString(),sha256:await digest(entries),entries};
 if(new Blob([JSON.stringify(result)]).size>BACKUP_LIMIT)throw Error('Backup exceeds 64 MB; export datasets separately');return result;
}
export async function decodeBackup(text:string):Promise<WorkspaceEntry[]>{
 if(new Blob([text]).size>BACKUP_LIMIT)fail();let b;try{b=JSON.parse(text)}catch{fail()}
 if(!object(b)||b.format!=='trading-strategy-lab-workspace'||b.version!==1||typeof b.createdAt!=='string'||!Number.isFinite(Date.parse(b.createdAt))||typeof b.sha256!=='string')fail();
 const entries=validateEntries(b.entries);if(await digest(entries)!==b.sha256)throw Error('Backup checksum mismatch; no data was changed');return entries;
}
