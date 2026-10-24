/** Research-only margin headroom on an OPEN paper position using a supplied bid/ask quote.
 * Neither collateral nor maintenance requirement is inferred from a broker account.
 */
import type {PaperIdentity,PaperOrder,PaperQuote} from './paper-execution.ts';
import type {PaperCashflow} from './paper-cashflow-reconciliation.ts';

export type PaperMarginScenario = Readonly<{
  label:string; asOf:number; cashEquityBeforePositionCurrency:number;
  assumedMaintenanceRequirementCurrency:number; otherReservedMarginCurrency:number;
  maxQuoteAgeSeconds:number; postedCashflows:readonly PaperCashflow[];
}>;
export type PaperMarginAssessment = Readonly<{
  orderId:string; label:string; asOf:number; markSide:'bid'|'ask'; markPrice:number;
  grossUnrealizedPnlCurrency:number; estimatedRoundTripCommissionCurrency:number;
  knownPostedCashflowsCurrency:number; estimatedAccountEquityCurrency:number;
  assumedTotalMaintenanceCurrency:number; headroomCurrency:number;
  state:'ABOVE_ASSUMED_MAINTENANCE'|'AT_OR_BELOW_ASSUMED_MAINTENANCE';
  coverage:'DECLARED_UNVERIFIED_SCENARIO';
}>;
const safeTime=(x:number)=>Number.isSafeInteger(x)&&x>=0;
const finite=(x:number)=>Number.isFinite(x);
const positive=(x:number)=>finite(x)&&x>0;
const nonnegative=(x:number)=>finite(x)&&x>=0;
const text=(x:string,max:number)=>typeof x==='string'&&x.trim().length>0&&x.length<=max;
const kinds=['OVERNIGHT_FINANCING','BORROW_FEE','FX_CONVERSION','BROKER_ADJUSTMENT'];

/** A breached *assumed* threshold is a stress flag, never a simulated broker liquidation. */
export function assessPaperMarginScenario(
  identity:PaperIdentity,order:PaperOrder,quote:PaperQuote,scenario:PaperMarginScenario
):PaperMarginAssessment {
  if (identity.priceSide!=='bid-ask'||!text(identity.instrument,160)||!text(identity.provider,160)||
      !text(identity.venue,160)||!positive(identity.pointValue)||
      order.status!=='OPEN'||order.instrument!==identity.instrument||
      (order.side!=='BUY'&&order.side!=='SELL')||!positive(order.units)||!positive(order.entry!)||
      !nonnegative(order.commissionPerUnitSide)||
      !safeTime(order.entryObservedAt!)||!safeTime(order.entryReceivedAt!)||
      order.entryReceivedAt!<order.entryObservedAt!) {
    throw Error('Valid open source-identified paper position required');
  }
  if (quote.instrument!==identity.instrument||quote.provider!==identity.provider||quote.venue!==identity.venue||
      !safeTime(quote.observedAt)||!safeTime(quote.receivedAt)||
      quote.observedAt>quote.receivedAt||quote.observedAt<order.entryObservedAt!||
      quote.receivedAt<order.entryReceivedAt!||!positive(quote.bid)||!positive(quote.ask)||
      quote.ask<quote.bid||!safeTime(scenario.asOf)||quote.receivedAt>scenario.asOf||
      !safeTime(scenario.maxQuoteAgeSeconds)||scenario.asOf-quote.observedAt>scenario.maxQuoteAgeSeconds) {
    throw Error('Stale, future, crossed or source-mismatched paper margin quote');
  }
  if (!text(scenario.label,100)||!finite(scenario.cashEquityBeforePositionCurrency)||
      !positive(scenario.assumedMaintenanceRequirementCurrency)||
      !nonnegative(scenario.otherReservedMarginCurrency)||
      !Array.isArray(scenario.postedCashflows)) {
    throw Error('Explicit finite account equity, maintenance assumptions and cashflows required');
  }
  const seen=new Map<string,PaperCashflow>();
  let knownPostedCashflowsCurrency=0;
  for(const c of scenario.postedCashflows){
    if(!text(c.id,80)||!text(c.reference,200)||c.orderId!==order.clientOrderId||
       c.instrument!==identity.instrument||c.provider!==identity.provider||c.venue!==identity.venue||
       !kinds.includes(c.kind)||!safeTime(c.at)||c.at<order.entryReceivedAt!||c.at>scenario.asOf||
       !finite(c.amountCurrency)) throw Error('Invalid or unprovenanced posted cashflow');
    const old=seen.get(c.id);
    if(old){
      if(Object.keys(old).some(k=>old[k as keyof PaperCashflow]!==c[k as keyof PaperCashflow]))
        throw Error('Conflicting duplicate posted cashflow ID');
      continue;
    }
    seen.set(c.id,{...c});
    knownPostedCashflowsCurrency+=c.amountCurrency;
    if(!finite(knownPostedCashflowsCurrency)) throw Error('Margin scenario cashflow overflow');
  }
  const markSide=order.side==='BUY'?'bid':'ask';
  const markPrice=quote[markSide];
  const grossUnrealizedPnlCurrency=(order.side==='BUY'?markPrice-order.entry!:order.entry!-markPrice)*order.units*identity.pointValue;
  const estimatedRoundTripCommissionCurrency=2*order.commissionPerUnitSide*order.units;
  const estimatedAccountEquityCurrency=scenario.cashEquityBeforePositionCurrency+
    grossUnrealizedPnlCurrency-estimatedRoundTripCommissionCurrency+knownPostedCashflowsCurrency;
  const assumedTotalMaintenanceCurrency=scenario.assumedMaintenanceRequirementCurrency+scenario.otherReservedMarginCurrency;
  const headroomCurrency=estimatedAccountEquityCurrency-assumedTotalMaintenanceCurrency;
  if(![grossUnrealizedPnlCurrency,estimatedRoundTripCommissionCurrency,estimatedAccountEquityCurrency,
       assumedTotalMaintenanceCurrency,headroomCurrency].every(finite)) throw Error('Non-finite paper margin arithmetic');
  return {orderId:order.clientOrderId,label:scenario.label,asOf:scenario.asOf,markSide,markPrice,
    grossUnrealizedPnlCurrency,estimatedRoundTripCommissionCurrency,knownPostedCashflowsCurrency,
    estimatedAccountEquityCurrency,assumedTotalMaintenanceCurrency,headroomCurrency,
    state:headroomCurrency<=0?'AT_OR_BELOW_ASSUMED_MAINTENANCE':'ABOVE_ASSUMED_MAINTENANCE',
    coverage:'DECLARED_UNVERIFIED_SCENARIO'};
}
