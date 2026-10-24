/**
 * Read-only, deterministic descriptive uncertainty for a frozen OHLC risk-path
 * report. No order execution, provider access, or claim of statistical edge.
 */
import type {RiskPathReport} from './sweep-confluence-risk-path.ts';

export type CostUncertainty = {
  roundTripCostBps:number;
  meanNetBps:number|null;meanNetR:number|null;
  lower95NetBps:number|null;upper95NetBps:number|null;
  lower95NetR:number|null;upper95NetR:number|null;
};
export type RiskPathUncertainty = {
  engine:'sweep-confluence-week-cluster-uncertainty-v1';
  datasetId:string;instrument:string;seed:string;
  trades:number;weeks:number;
  stopExits:number;targetExits:number;timeExits:number;
  status:'INSUFFICIENT_EVIDENCE'|'DESCRIPTIVE_ONLY';
  scenarios:CostUncertainty[];warning:string;
};
const WEEK=604800,MONDAY=345600,REPS=3000;
function near(a:number,b:number):boolean{
 return Number.isFinite(a)&&Number.isFinite(b)&&Math.abs(a-b)<=1e-8*Math.max(1,Math.abs(a),Math.abs(b));
}
function hash32(s:string):number{
 let h=2166136261;
 for(let i=0;i<s.length;i++)h=Math.imul(h^s.charCodeAt(i),16777619);
 return (h>>>0)||0x9e3779b9;
}
function percentile(sorted:readonly number[],q:number):number{
 const at=(sorted.length-1)*q,lo=Math.floor(at),hi=Math.ceil(at);
 return sorted[lo]+(sorted[hi]-sorted[lo])*(at-lo);
}
function mean(xs:readonly number[]):number|null{
 if(!xs.length)return null;
 let m=0;
 for(let i=0;i<xs.length;i++){
  m+=(xs[i]-m)/(i+1);
  if(!Number.isFinite(m))throw Error('Nonfinite mean');
 }
 return m;
}
export function estimateConfluenceRiskPathUncertainty(
 report:RiskPathReport,seed='locked-risk-path-week-v1'
):RiskPathUncertainty{
 if(report.engine!=='sweep-confluence-ohlc-risk-path-v1'||
   report.sourceEngine!=='sweep-mss-fvg-same-close-v1'||
   !report.datasetId?.trim()||!report.instrument?.trim())
  throw Error('Exact risk-path engine and source identity required');
 if(!seed.trim()||seed.length>128)throw Error('Frozen seed required');
 const costs=report.config?.roundTripCostsBps;
 if(!Array.isArray(costs)||costs.length<1||costs.length>10||
   costs.some((v,i)=>!Number.isFinite(v)||v<0||v>10000||(i>0&&v<=costs[i-1])))
  throw Error('Invalid cost scenarios');
 if(!Number.isSafeInteger(report.config.atrPeriod)||report.config.atrPeriod<2||
   !Number.isFinite(report.config.stopAtrMultiple)||report.config.stopAtrMultiple<=0||
   !Number.isFinite(report.config.rewardRisk)||report.config.rewardRisk<1||
   !Number.isSafeInteger(report.config.maxHoldBars)||report.config.maxHoldBars<1)
  throw Error('Invalid frozen path parameters');
 const counters=[report.inputSignals,report.closed,report.pending,report.gapExcluded,
  report.warmupExcluded,report.overlapExcluded,report.priceExcluded];
 if(counters.some(v=>!Number.isSafeInteger(v)||v<0)||
   report.inputSignals!==report.closed+report.pending+report.gapExcluded+
    report.warmupExcluded+report.overlapExcluded+report.priceExcluded||
   !Array.isArray(report.trades)||report.trades.length!==report.closed||report.trades.length>100000)
  throw Error('Invalid risk-path accounting');
 if(!Array.isArray(report.meanNetBps)||!Array.isArray(report.meanNetR)||
   report.meanNetBps.length!==costs.length||report.meanNetR.length!==costs.length)
  throw Error('Invalid scenario means');
 const weeks=new Map<number,{bps:number[];r:number[];n:number}>();
 let prevExit=-Infinity,stopExits=0,targetExits=0,timeExits=0;
 for(const t of report.trades){
  if(!Number.isSafeInteger(t.sweepAt)||!Number.isSafeInteger(t.confirmationAt)||
     !Number.isSafeInteger(t.entryAt)||!Number.isSafeInteger(t.exitAt)||
     t.sweepAt>=t.confirmationAt||t.entryAt!==t.confirmationAt||
     t.entryAt<prevExit||t.exitAt<=t.entryAt||
     !['bullish','bearish'].includes(t.direction)||
     !['STOP','TARGET','TIME'].includes(t.reason))
   throw Error('Invalid trade chronology or prices');
  if(![t.entry,t.stop,t.target,t.exit].every(v=>Number.isFinite(v)&&v>0)||
     !Number.isFinite(t.grossBps))throw Error('Invalid trade prices or gross return');
  const sign=t.direction==='bullish'?1:-1;
  const risk=sign*(t.entry-t.stop);
  if(risk<=0||!Number.isFinite(risk)||
     !near(t.target,t.entry+sign*risk*report.config.rewardRisk)||
     !near(t.grossBps,sign*(t.exit/t.entry-1)*10000)||
     (t.reason==='TARGET'&&!near(t.exit,t.target))||
     (t.reason==='STOP'&&sign*(t.exit-t.stop)>1e-8*Math.max(1,t.entry)))
   throw Error('Inconsistent stop, target, exit or gross return');
  if(!Array.isArray(t.netBps)||!Array.isArray(t.netR)||
     t.netBps.length!==costs.length||t.netR.length!==costs.length)
   throw Error('Invalid trade scenario arrays');
  const riskBps=risk/t.entry*10000;
  const w=Math.floor((t.entryAt-MONDAY)/WEEK);
  const group=weeks.get(w)||{bps:costs.map(()=>0),r:costs.map(()=>0),n:0};
  for(let j=0;j<costs.length;j++){
   if(!near(t.netBps[j],t.grossBps-costs[j])||
      !near(t.netR[j],(t.grossBps-costs[j])/riskBps))
    throw Error('Inconsistent net costs or R accounting');
   group.bps[j]+=t.netBps[j];group.r[j]+=t.netR[j];
   if(!Number.isFinite(group.bps[j])||!Number.isFinite(group.r[j]))
    throw Error('Overflowed week sum');
  }
  group.n++;weeks.set(w,group);prevExit=t.exitAt;
  if(t.reason==='STOP')stopExits++;
  else if(t.reason==='TARGET')targetExits++;
  else timeExits++;
 }
 const scenarios:CostUncertainty[]=costs.map((cost,j)=>{
  const bps=mean(report.trades.map(t=>t.netBps[j]));
  const r=mean(report.trades.map(t=>t.netR[j]));
  if((bps===null)!==(report.meanNetBps[j]===null)||
     (r===null)!==(report.meanNetR[j]===null)||
     (bps!==null&&!near(bps,report.meanNetBps[j]!))||
     (r!==null&&!near(r,report.meanNetR[j]!)))
   throw Error('Reported mean does not match trades');
  return {roundTripCostBps:cost,meanNetBps:bps,meanNetR:r,
   lower95NetBps:null,upper95NetBps:null,lower95NetR:null,upper95NetR:null};
 });
 const count=report.trades.length,weekCount=weeks.size;
 const sufficient=count>=30&&weekCount>=12;
 if(sufficient){
  const groups=[...weeks].sort((a,b)=>a[0]-b[0]).map(([,g])=>g);
  let state=hash32([report.datasetId,report.instrument,report.engine,seed,
    report.config.atrPeriod,report.config.stopAtrMultiple,
    report.config.rewardRisk,report.config.maxHoldBars].join('|'));
  const draw=()=>{state^=state<<13;state^=state>>>17;state^=state<<5;return (state>>>0)/4294967296};
  const bpsSamples=costs.map(()=>[] as number[]),rSamples=costs.map(()=>[] as number[]);
  for(let rep=0;rep<REPS;rep++){
   const bps=costs.map(()=>0),rs=costs.map(()=>0);let n=0;
   for(let k=0;k<weekCount;k++){
    const g=groups[Math.floor(draw()*weekCount)];n+=g.n;
    for(let j=0;j<costs.length;j++){bps[j]+=g.bps[j];rs[j]+=g.r[j]}
   }
   if(!n)throw Error('Empty bootstrap draw');
   for(let j=0;j<costs.length;j++){
    const a=bps[j]/n,b=rs[j]/n;
    if(!Number.isFinite(a)||!Number.isFinite(b))throw Error('Nonfinite bootstrap draw');
    bpsSamples[j].push(a);rSamples[j].push(b);
   }
  }
  for(let j=0;j<costs.length;j++){
   bpsSamples[j].sort((a,b)=>a-b);rSamples[j].sort((a,b)=>a-b);
   scenarios[j].lower95NetBps=percentile(bpsSamples[j],.025);
   scenarios[j].upper95NetBps=percentile(bpsSamples[j],.975);
   scenarios[j].lower95NetR=percentile(rSamples[j],.025);
   scenarios[j].upper95NetR=percentile(rSamples[j],.975);
  }
 }
 return {engine:'sweep-confluence-week-cluster-uncertainty-v1',
  datasetId:report.datasetId,instrument:report.instrument,seed,trades:count,weeks:weekCount,
  stopExits,targetExits,timeExits,
  status:sufficient?'DESCRIPTIVE_ONLY':'INSUFFICIENT_EVIDENCE',scenarios,
  warning:'Descriptive UTC-calendar-week cluster bootstrap; assumes independent weeks and does not adjust for multiple testing, overlapping market regimes, previously inspected samples, selection bias, BID-only prices, spreads, slippage, financing or executable fills. No statistical significance or profitable edge is established.'};
}
