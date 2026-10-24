/**
 * Offline, read-only downside diagnostics for the disconnected paper journal.
 * Replays original caller-supplied events rather than trusting a caller-provided
 * P&L summary. Never authenticates quotes or enables execution.
 */
import {replayDisconnectedPaperLedger} from './disconnected-paper-ledger.ts';
import type {PaperEvent,PaperPolicy,PaperSource} from './disconnected-paper-ledger.ts';

export type PaperDownsideAudit={
 mode:'UNVERIFIED_LOCAL_RESEARCH';live:false;quoteAuthenticated:false;
 execution:'NONE';persisted:false;
 closedTrades:number;openPositions:0|1;quoteObservations:number;
 realizedNetCash:number;unrealizedNetCash:number;
 realizedReturnPct:number;markToMarketReturnPct:number;
 grossWinningCash:number;grossLosingCash:number;
 profitFactor:number|null;averageClosedNetCash:number|null;
 medianClosedNetCash:number|null;worstClosedNetCash:number|null;
 maxConsecutiveLosses:number;feesCash:number;
 observedMaxDrawdownCash:number;observedMaxDrawdownPct:number;
 observedMaxUnderwaterSeconds:number;unrecoveredAtLastObservation:boolean;
};

/** Observed event-path diagnostics, not an independent forward backtest.
 * Profit factor is null if no losing closed trade (never report infinity).
 * Zero closed trades produce null per-trade statistics, not a 0% win claim.
 * Underwater duration starts at the FIRST observed below-peak snapshot, not
 * the unknowable intrabar drawdown start, and is therefore only a lower bound.
 */
export function auditDisconnectedPaperDownside(
 events:readonly PaperEvent[],source:PaperSource,policy:PaperPolicy,
):PaperDownsideAudit{
 const replay=replayDisconnectedPaperLedger(events,source,policy);
 const pnl=replay.closedTrades.map(t=>t.netPnl);
 let gains=0,losses=0,streak=0,maxStreak=0;
 for(const n of pnl){
  if(n>0){gains+=n;streak=0;}
  else if(n<0){losses-=n;streak++;maxStreak=Math.max(maxStreak,streak);}
  else streak=0;
 }
 const sorted=[...pnl].sort((a,b)=>a-b),count=sorted.length;
 const median=count===0?null:count%2===1?sorted[(count-1)/2]:
  (sorted[count/2-1]/2+sorted[count/2]/2);
 let observedPeak=policy.startingCash;
 let underwaterSince:number|null=null,maxUnderwater=0;
 for(const s of replay.snapshots){
  if(s.equity>=observedPeak){
   if(underwaterSince!==null){
    maxUnderwater=Math.max(maxUnderwater,s.at-underwaterSince);
    underwaterSince=null;
   }
   observedPeak=s.equity;
  }else if(underwaterSince===null)underwaterSince=s.at;
 }
 if(underwaterSince!==null&&replay.snapshots.length){
  maxUnderwater=Math.max(maxUnderwater,replay.snapshots[replay.snapshots.length-1].at-underwaterSince);
 }
 const factor=losses>0?gains/losses:null;
 const values=[gains,losses,maxUnderwater,replay.realizedNet,replay.unrealizedNet,
  replay.maxDrawdownCash,replay.maxDrawdownPct,median??0,factor??0];
 if(values.some(x=>!Number.isFinite(x)))throw Error('Nonfinite offline paper downside diagnostic');
 return {
  mode:'UNVERIFIED_LOCAL_RESEARCH',live:false,quoteAuthenticated:false,
  execution:'NONE',persisted:false,
  closedTrades:count,openPositions:replay.openPosition?1:0,quoteObservations:replay.quotes,
  realizedNetCash:replay.realizedNet,unrealizedNetCash:replay.unrealizedNet,
  realizedReturnPct:100*replay.realizedNet/policy.startingCash,
  markToMarketReturnPct:100*(replay.equity-policy.startingCash)/policy.startingCash,
  grossWinningCash:gains,grossLosingCash:losses,profitFactor:factor,
  averageClosedNetCash:count?replay.realizedNet/count:null,
  medianClosedNetCash:median,worstClosedNetCash:count?sorted[0]:null,
  maxConsecutiveLosses:maxStreak,feesCash:replay.totalFees,
  observedMaxDrawdownCash:replay.maxDrawdownCash,
  observedMaxDrawdownPct:replay.maxDrawdownPct,
  observedMaxUnderwaterSeconds:maxUnderwater,
  unrecoveredAtLastObservation:underwaterSince!==null,
 };
}
