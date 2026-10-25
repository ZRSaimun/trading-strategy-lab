/**
 * Isolated, deterministic OHLC risk-path experiment for completed confluence
 * observations. This is NOT a broker, order router, or executable fill model.
 * Entry at next bar open; stop distance uses only candles closed before entry.
 */
import {validStructureSegments} from './structure-quality.ts';
import type {Bar} from './research.ts';
import type {ConfluenceStudy} from './sweep-confluence-study.ts';

export type RiskPathConfig={
 atrPeriod:number;stopAtrMultiple:number;rewardRisk:number;
 maxHoldBars:number;roundTripCostsBps:readonly number[];
};
export type RiskPathTrade={
 sweepAt:number;confirmationAt:number;entryAt:number;exitAt:number;
 direction:'bullish'|'bearish';entry:number;stop:number;target:number;
 exit:number;reason:'STOP'|'TARGET'|'TIME';grossBps:number;
 netBps:number[];netR:number[];
};
export type RiskPathReport={
 engine:'sweep-confluence-ohlc-risk-path-v1';datasetId:string;instrument:string;
 sourceEngine:'sweep-mss-fvg-same-close-v1';config:RiskPathConfig;
 inputSignals:number;closed:number;pending:number;gapExcluded:number;
 warmupExcluded:number;overlapExcluded:number;priceExcluded:number;
 trades:RiskPathTrade[];meanNetBps:(number|null)[];meanNetR:(number|null)[];
 warning:string;
};
const H=3600;
function avg(values:readonly number[]):number|null{
 if(!values.length)return null;
 let result=0;
 for(let i=0;i<values.length;i++)result+=(values[i]-result)/(i+1);
 return Number.isFinite(result)?result:null;
}
function configCheck(c:RiskPathConfig,horizon:number){
 if(!Number.isSafeInteger(c.atrPeriod)||c.atrPeriod<2||c.atrPeriod>100)
  throw Error('ATR period must be 2–100');
 if(!Number.isFinite(c.stopAtrMultiple)||c.stopAtrMultiple<=0||c.stopAtrMultiple>10)
  throw Error('Stop ATR multiple must be positive and at most 10');
 if(!Number.isFinite(c.rewardRisk)||c.rewardRisk<1||c.rewardRisk>20)
  throw Error('Reward/risk must be 1–20');
 if(!Number.isSafeInteger(c.maxHoldBars)||c.maxHoldBars<1||c.maxHoldBars>horizon)
  throw Error('Holding horizon must fit the predeclared confluence outcome horizon');
 if(!Array.isArray(c.roundTripCostsBps)||!c.roundTripCostsBps.length||
   c.roundTripCostsBps.length>10||c.roundTripCostsBps.some((x,i)=>
    !Number.isFinite(x)||x<0||x>10000||(i>0&&x<=c.roundTripCostsBps[i-1])))
  throw Error('Round-trip costs must be finite, sorted and unique');
}
export function simulateConfluenceRiskPath(
 bars:readonly Bar[],study:ConfluenceStudy,cfg:RiskPathConfig
):RiskPathReport{
 if(study.engine!=='sweep-mss-fvg-same-close-v1'||study.frame!=='1H'||
   !study.datasetId?.trim()||!study.instrument?.trim())
  throw Error('Exact 1H confluence study identity required');
 configCheck(cfg,study.horizonBars);
 if(bars.length>1_000_000||study.signals.length>1_000_000)
  throw Error('Bounded research input exceeded');
 const segments=validStructureSegments(bars,'1H');
 const indices=new Map<number,number>();
 for(let i=0;i<bars.length;i++){
  if(i>0&&bars[i].time<=bars[i-1].time)throw Error('Unordered or duplicate bars');
  if(segments[i]>=0)indices.set(bars[i].time,i);
 }
 const signals=[...study.signals].sort((a,b)=>a.entryAt-b.entryAt||a.sweepAt-b.sweepAt);
 const trades:RiskPathTrade[]=[];
 let pending=0,gapExcluded=0,warmupExcluded=0,overlapExcluded=0,priceExcluded=0;
 let busyUntil=-Infinity;
 for(const s of signals){
  if(!Number.isSafeInteger(s.entryAt)||!Number.isSafeInteger(s.confirmationAt)||
    !Number.isSafeInteger(s.sweepAt)||s.sweepAt>=s.confirmationAt||
    s.confirmationAt!==s.entryAt||!['bullish','bearish'].includes(s.direction))
   throw Error('Invalid causal confluence signal');
  const i=indices.get(s.entryAt);
  if(i===undefined){gapExcluded++;continue}
  if(s.entry!==bars[i].open)throw Error('Entry price does not match immutable next-open candle');
  if(i<1||segments[i]!==segments[i-1]){gapExcluded++;continue}
  if(s.entryAt<busyUntil){overlapExcluded++;continue}
  const confirmation=i-1;
  if(confirmation-cfg.atrPeriod<segments[confirmation]){
   warmupExcluded++;continue;
  }
  let trSum=0;
  for(let k=confirmation-cfg.atrPeriod+1;k<=confirmation;k++){
   const b=bars[k],prev=bars[k-1].close;
   trSum+=Math.max(b.high-b.low,Math.abs(b.high-prev),Math.abs(b.low-prev));
  }
  const entry=bars[i].open,stopDistance=trSum/cfg.atrPeriod*cfg.stopAtrMultiple;
  const sign=s.direction==='bullish'?1:-1;
  const stop=entry-sign*stopDistance,target=entry+sign*stopDistance*cfg.rewardRisk;
  if(![entry,stopDistance,stop,target].every(Number.isFinite)||
    entry<=0||stopDistance<=0||stop<=0||target<=0){
   priceExcluded++;continue;
  }
  let outcome:{k:number;exit:number;reason:RiskPathTrade['reason']}|null=null;
  let excluded=false;
  for(let k=i;k<i+cfg.maxHoldBars;k++){
   if(k>=bars.length){pending++;excluded=true;break}
   if(segments[k]!==segments[i]){gapExcluded++;excluded=true;break}
   const b=bars[k];
   const adverseOpen=sign===1?b.open<=stop:b.open>=stop;
   const favorableOpen=sign===1?b.open>=target:b.open<=target;
   const adverseWick=sign===1?b.low<=stop:b.high>=stop;
   const favorableWick=sign===1?b.high>=target:b.low<=target;
   // Stop-first for ambiguous intrabar paths; adverse opening gaps fill at
   // opening price (worse than stop), favorable gaps get no improvement.
   if(adverseOpen)outcome={k,exit:b.open,reason:'STOP'};
   else if(favorableOpen)outcome={k,exit:target,reason:'TARGET'};
   else if(adverseWick)outcome={k,exit:stop,reason:'STOP'};
   else if(favorableWick)outcome={k,exit:target,reason:'TARGET'};
   else if(k===i+cfg.maxHoldBars-1)outcome={k,exit:b.close,reason:'TIME'};
   if(outcome)break;
  }
  if(excluded){busyUntil=Infinity;continue}
  if(!outcome)throw Error('Internal outcome accounting error');
  const grossBps=sign*(outcome.exit/entry-1)*10000;
  const riskBps=stopDistance/entry*10000;
  if(!Number.isFinite(grossBps)||!Number.isFinite(riskBps)||riskBps<=0||
    cfg.roundTripCostsBps.some(cost=>!Number.isFinite((grossBps-cost)/riskBps))){
   priceExcluded++;busyUntil=Infinity;continue;
  }
  const netBps=cfg.roundTripCostsBps.map(cost=>grossBps-cost);
  trades.push({sweepAt:s.sweepAt,confirmationAt:s.confirmationAt,
   entryAt:s.entryAt,exitAt:bars[outcome.k].time+H,direction:s.direction,
   entry,stop,target,exit:outcome.exit,reason:outcome.reason,grossBps,
   netBps,netR:netBps.map(x=>x/riskBps)});
  busyUntil=bars[outcome.k].time+H;
 }
 return {engine:'sweep-confluence-ohlc-risk-path-v1',
  datasetId:study.datasetId,instrument:study.instrument,
  sourceEngine:'sweep-mss-fvg-same-close-v1',
  config:{...cfg,roundTripCostsBps:[...cfg.roundTripCostsBps]},
  inputSignals:signals.length,closed:trades.length,pending,gapExcluded,
  warmupExcluded,overlapExcluded,priceExcluded,trades,
  meanNetBps:cfg.roundTripCostsBps.map((_,j)=>avg(trades.map(t=>t.netBps[j]))),
  meanNetR:cfg.roundTripCostsBps.map((_,j)=>avg(trades.map(t=>t.netR[j]))),
  warning:'Research-only deterministic BID/OHLC path; stop-first same-bar ambiguity, adverse gap at open, hypothetical round-trip costs. ATR through confirmation close only. No broker bid/ask, financing, margin, contract sizing, slippage distribution, authenticated feed, untouched holdout or verified profitable edge. No live or paper orders placed.'};
}
