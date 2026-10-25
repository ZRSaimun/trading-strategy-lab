/**
 * Frozen, offline friction sensitivity for hypothetical completed OHLC risk paths.
 * Replaces (never adds to) the report's illustrative flat round-trip costs.
 * No quotes, broker connection, actual fills, funding calendar or orders.
 */
import type {RiskPathReport} from './sweep-confluence-risk-path.ts';
import {summarizeRiskPathCostRegimes} from './sweep-risk-path-regime-stress.ts';

export type FrictionAssumption={
 id:string;
 roundTripSpreadBps:number;
 entrySlippageBps:number;
 exitSlippageBps:number;
 roundTripCommissionBps:number;
 financingBpsPer24Hours:number;
};
export type FrictionScenarioResult={
 id:string;trades:number;meanGrossBps:number|null;meanAssumedCostBps:number|null;
 meanNetBps:number|null;meanNetR:number|null;netPositiveFraction:number|null;
 minAssumedCostBps:number|null;maxAssumedCostBps:number|null;
};
export type FrictionStressReport={
 engine:'sweep-confluence-friction-sensitivity-v1';
 datasetId:string;instrument:string;sourceEngine:string;
 scenarios:FrictionScenarioResult[];status:'SENSITIVITY_ONLY';
 warning:string;
};
const MAX_COMPONENT_BPS=1000;
function average(xs:readonly number[]):number|null{
 if(xs.length===0)return null;
 let m=0;
 for(let i=0;i<xs.length;i++){
  m+=(xs[i]-m)/(i+1);
  if(!Number.isFinite(m))throw Error('Nonfinite friction mean');
 }
 return m;
}
export function stressConfluenceFriction(
 report:RiskPathReport,assumptions:readonly FrictionAssumption[]
):FrictionStressReport{
 // The existing independent auditor verifies source identity, all path arithmetic,
 // no overlapping trades, stop geometry, and the original cost scenario means.
 summarizeRiskPathCostRegimes(report);
 if(!Array.isArray(assumptions)||assumptions.length<1||assumptions.length>10)
  throw Error('Provide 1–10 frozen friction scenarios');
 const seen=new Set<string>();
 for(const a of assumptions){
  if(!a||typeof a.id!=='string'||!/^[A-Za-z0-9_-]{1,40}$/.test(a.id)||seen.has(a.id))
   throw Error('Invalid or repeated scenario ID');
  seen.add(a.id);
  for(const key of ['roundTripSpreadBps','entrySlippageBps','exitSlippageBps','roundTripCommissionBps','financingBpsPer24Hours'] as const){
   if(!Number.isFinite(a[key])||a[key]<0||a[key]>MAX_COMPONENT_BPS)
    throw Error('Invalid nonnegative bounded friction component: '+key);
  }
 }
 const scenarios=assumptions.map(a=>{
  const gross:number[]=[],costs:number[]=[],nets:number[]=[],rs:number[]=[];
  let positive=0,min=Infinity,max=-Infinity;
  for(const t of report.trades){
   const seconds=t.exitAt-t.entryAt;
   // A completed 1H path must not silently finance unobserved time.
   if(!Number.isSafeInteger(seconds)||seconds<=0||
      seconds>report.config.maxHoldBars*3600)
    throw Error('Invalid elapsed holding interval for 1H risk path');
   const elapsedDays=seconds/86400;
   const assumedCost=a.roundTripSpreadBps+a.entrySlippageBps+
    a.exitSlippageBps+a.roundTripCommissionBps+
    a.financingBpsPer24Hours*elapsedDays;
   const sign=t.direction==='bullish'?1:-1;
   const riskBps=sign*(t.entry-t.stop)/t.entry*10000;
   const net=t.grossBps-assumedCost,r=net/riskBps;
   if(![assumedCost,net,r].every(Number.isFinite)||riskBps<=0)
    throw Error('Nonfinite friction-adjusted result');
   gross.push(t.grossBps);costs.push(assumedCost);nets.push(net);rs.push(r);
   if(net>0)positive++;
   min=Math.min(min,assumedCost);max=Math.max(max,assumedCost);
  }
  return {id:a.id,trades:report.trades.length,meanGrossBps:average(gross),
   meanAssumedCostBps:average(costs),meanNetBps:average(nets),
   meanNetR:average(rs),netPositiveFraction:report.trades.length?positive/report.trades.length:null,
   minAssumedCostBps:costs.length?min:null,maxAssumedCostBps:costs.length?max:null};
 });
 return {engine:'sweep-confluence-friction-sensitivity-v1',datasetId:report.datasetId,
  instrument:report.instrument,sourceEngine:report.engine,scenarios,status:'SENSITIVITY_ONLY',
  warning:'Illustrative friction assumptions REPLACE the source report flat cost, never add to it. Round-trip spread/commission, adverse entry/exit slippage and elapsed-UTC financing are sensitivity inputs, not observed broker quotes, swap cutoffs, actual cash fees, fill prices, margin or validated executable P&L. BID-only historical candles cannot establish executable costs or a profitable edge. No live or paper orders.'};
}
