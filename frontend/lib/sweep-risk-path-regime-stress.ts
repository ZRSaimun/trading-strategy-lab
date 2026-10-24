/**
 * Offline descriptive cost and UTC-year regime stress for frozen OHLC paths.
 * No signal selection, broker access, orders, or portfolio equity claims.
 */
import type {RiskPathReport,RiskPathTrade} from './sweep-confluence-risk-path.ts';
export type CostSlice={roundTripCostBps:number;trades:number;meanNetBps:number|null;meanNetR:number|null;positiveNetRate:number|null;longestLosingRun:number;maxAdditiveRDrawdown:number|null;worstNetR:number|null;bestNetR:number|null};
export type AnnualRegime={utcEntryYear:number;trades:number;eventWeeks:number;scenarios:CostSlice[]};
export type RegimeStress={engine:'sweep-confluence-cost-regime-stress-v1';datasetId:string;instrument:string;trades:number;eventWeeks:number;meanBpsBreakevenCost:number|null;meanRBreakevenCost:number|null;scenarios:CostSlice[];annual:AnnualRegime[];warning:string};
const WEEK=604800,MONDAY=345600;
function near(a:number,b:number){return Number.isFinite(a)&&Number.isFinite(b)&&Math.abs(a-b)<=1e-8*Math.max(1,Math.abs(a),Math.abs(b))}
function avg(xs:readonly number[]):number|null{
 if(!xs.length)return null;
 let m=0;
 for(let i=0;i<xs.length;i++){m+=(xs[i]-m)/(i+1);if(!Number.isFinite(m))throw Error('Nonfinite mean')}
 return m;
}
function slice(ts:readonly RiskPathTrade[],costs:readonly number[]):CostSlice[]{
 return costs.map((cost,j)=>{
  let cumulative=0,peak=0,drawdown=0,losing=0,longest=0,positive=0;
  const rs:number[]=[],bps:number[]=[];
  for(const t of ts){
   const r=t.netR[j];rs.push(r);bps.push(t.netBps[j]);
   if(r>0)positive++;
   if(r<0){losing++;longest=Math.max(longest,losing)}else losing=0;
   cumulative+=r;if(!Number.isFinite(cumulative))throw Error('Nonfinite cumulative R');
   peak=Math.max(peak,cumulative);drawdown=Math.max(drawdown,peak-cumulative);
  }
  return {roundTripCostBps:cost,trades:ts.length,meanNetBps:avg(bps),meanNetR:avg(rs),
   positiveNetRate:ts.length?positive/ts.length:null,longestLosingRun:longest,
   maxAdditiveRDrawdown:ts.length?drawdown:null,
   worstNetR:ts.length?Math.min(...rs):null,bestNetR:ts.length?Math.max(...rs):null};
 });
}
export function summarizeRiskPathCostRegimes(report:RiskPathReport):RegimeStress{
 if(report.engine!=='sweep-confluence-ohlc-risk-path-v1'||report.sourceEngine!=='sweep-mss-fvg-same-close-v1'||!report.datasetId?.trim()||!report.instrument?.trim())throw Error('Exact source and engine identity required');
 const costs=report.config?.roundTripCostsBps;
 if(!Array.isArray(costs)||!costs.length||costs.length>10||costs.some((v,i)=>!Number.isFinite(v)||v<0||v>10000||(i>0&&v<=costs[i-1])))throw Error('Invalid frozen costs');
 if(!Number.isSafeInteger(report.config.atrPeriod)||report.config.atrPeriod<2||!Number.isFinite(report.config.stopAtrMultiple)||report.config.stopAtrMultiple<=0||!Number.isFinite(report.config.rewardRisk)||report.config.rewardRisk<1||!Number.isSafeInteger(report.config.maxHoldBars)||report.config.maxHoldBars<1)throw Error('Invalid frozen parameters');
 const counts=[report.inputSignals,report.closed,report.pending,report.gapExcluded,report.warmupExcluded,report.overlapExcluded,report.priceExcluded];
 if(counts.some(x=>!Number.isSafeInteger(x)||x<0)||report.inputSignals!==report.closed+report.pending+report.gapExcluded+report.warmupExcluded+report.overlapExcluded+report.priceExcluded||!Array.isArray(report.trades)||report.trades.length!==report.closed||report.trades.length>100000)throw Error('Inconsistent report accounting');
 if(!Array.isArray(report.meanNetBps)||!Array.isArray(report.meanNetR)||report.meanNetBps.length!==costs.length||report.meanNetR.length!==costs.length)throw Error('Invalid reported means');
 const years=new Map<number,RiskPathTrade[]>(),weeks=new Set<number>();
 const gross:number[]=[],grossR:number[]=[],inverseRisk:number[]=[];
 let previousExit=-Infinity;
 for(const t of report.trades){
  if(![t.sweepAt,t.confirmationAt,t.entryAt,t.exitAt].every(Number.isSafeInteger)||t.sweepAt>=t.confirmationAt||t.entryAt!==t.confirmationAt||t.entryAt<previousExit||t.exitAt<=t.entryAt||t.entryAt<0||t.entryAt>4102444800||!['bullish','bearish'].includes(t.direction)||!['STOP','TARGET','TIME'].includes(t.reason))throw Error('Invalid or overlapping chronology');
  if(![t.entry,t.stop,t.target,t.exit,t.grossBps].every(Number.isFinite)||[t.entry,t.stop,t.target,t.exit].some(x=>x<=0))throw Error('Invalid trade price');
  const sign=t.direction==='bullish'?1:-1,risk=sign*(t.entry-t.stop),riskBps=risk/t.entry*10000;
  if(!Number.isFinite(riskBps)||riskBps<=0||!near(t.target,t.entry+sign*risk*report.config.rewardRisk)||!near(t.grossBps,sign*(t.exit/t.entry-1)*10000)||(t.reason==='TARGET'&&!near(t.exit,t.target))||(t.reason==='STOP'&&sign*(t.exit-t.stop)>1e-8*Math.max(1,t.entry)))throw Error('Inconsistent gross return or stop/target');
  if(!Array.isArray(t.netBps)||!Array.isArray(t.netR)||t.netBps.length!==costs.length||t.netR.length!==costs.length)throw Error('Invalid cost arrays');
  for(let j=0;j<costs.length;j++)if(!near(t.netBps[j],t.grossBps-costs[j])||!near(t.netR[j],(t.grossBps-costs[j])/riskBps))throw Error('Cost/R arithmetic mismatch');
  gross.push(t.grossBps);grossR.push(t.grossBps/riskBps);inverseRisk.push(1/riskBps);
  const year=new Date(t.entryAt*1000).getUTCFullYear(),group=years.get(year)||[];
  group.push(t);years.set(year,group);weeks.add(Math.floor((t.entryAt-MONDAY)/WEEK));
  previousExit=t.exitAt;
 }
 const scenarios=slice(report.trades,costs);
 for(let j=0;j<costs.length;j++){
  const a=scenarios[j].meanNetBps,b=scenarios[j].meanNetR;
  if((a===null)!==(report.meanNetBps[j]===null)||(b===null)!==(report.meanNetR[j]===null)||(a!==null&&!near(a,report.meanNetBps[j]!))||(b!==null&&!near(b,report.meanNetR[j]!)))throw Error('Reported means mismatch');
 }
 const grossMean=avg(gross),grossRMean=avg(grossR),invMean=avg(inverseRisk);
 const meanRBreakevenCost=grossRMean===null||invMean===null?null:grossRMean/invMean;
 if(meanRBreakevenCost!==null&&!Number.isFinite(meanRBreakevenCost))throw Error('Nonfinite break-even');
 return {engine:'sweep-confluence-cost-regime-stress-v1',datasetId:report.datasetId,instrument:report.instrument,trades:report.trades.length,eventWeeks:weeks.size,meanBpsBreakevenCost:grossMean,meanRBreakevenCost,scenarios,
  annual:[...years].sort((a,b)=>a[0]-b[0]).map(([year,ts])=>({utcEntryYear:year,trades:ts.length,eventWeeks:new Set(ts.map(t=>Math.floor((t.entryAt-MONDAY)/WEEK))).size,scenarios:slice(ts,costs)})),
  warning:'Retrospective BID/OHLC descriptive stress only. Break-even costs are signed hypothetical round-trip bps, not broker executable spreads. Drawdown is additive R, NOT account equity or leverage. UTC years are not untouched holdouts. No financing, real fills, multiple-trial correction, statistically verified edge or real orders.'};
}