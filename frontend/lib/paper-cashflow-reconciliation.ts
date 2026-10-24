/** Read-only reconciliation of explicit cashflows against a CLOSED paper order.
 * Cashflows must be supplied by the caller; no broker fees, funding rates or calendars are invented.
 */
import type {PaperIdentity,PaperOrder} from './paper-execution.ts';

export type PaperCashflowKind = 'OVERNIGHT_FINANCING' | 'BORROW_FEE' | 'FX_CONVERSION' | 'BROKER_ADJUSTMENT';
export type PaperCashflow = Readonly<{
  id: string; orderId: string; instrument: string; provider: string; venue: string;
  at: number; kind: PaperCashflowKind; amountCurrency: number; reference: string;
}>;
export type PaperCashflowReconciliation = Readonly<{
  orderId: string; asOf: number; basePaperPnlCurrency: number;
  cashflowCurrency: Readonly<Record<PaperCashflowKind,number>>;
  knownCashflowAdjustedPnlCurrency: number; acceptedCashflows: number;
  coverage: 'PARTIAL_UNVERIFIED';
}>;
const kinds: readonly PaperCashflowKind[] = ['OVERNIGHT_FINANCING','BORROW_FEE','FX_CONVERSION','BROKER_ADJUSTMENT'];
const validTime = (v:number) => Number.isSafeInteger(v) && v>=0;
const validText = (v:string,max:number) => typeof v==='string' && v.trim().length>0 && v.length<=max;
const positive = (v:number) => Number.isFinite(v) && v>0;
const nonnegative = (v:number) => Number.isFinite(v) && v>=0;
// Floating-point products are compared at a few ULPs, not with a large
// absolute currency tolerance that could hide small forged commissions.
const sameAmount = (a:number,b:number) =>
  Number.isFinite(a) && Number.isFinite(b) &&
  Math.abs(a-b) <= 32*Number.EPSILON*Math.max(1,Math.abs(a),Math.abs(b));

/** The result is NOT broker net P&L unless every charge and source is independently reconciled. */
export function reconcilePaperCashflows(
  identity:PaperIdentity,order:PaperOrder,asOf:number,cashflows:readonly PaperCashflow[]
):PaperCashflowReconciliation {
  if (!validTime(asOf) || identity.priceSide!=='bid-ask' || !positive(identity.pointValue) ||
      !validText(identity.instrument,160) || !validText(identity.provider,160) || !validText(identity.venue,160) ||
      order.status!=='CLOSED' || order.instrument!==identity.instrument ||
      !validText(order.clientOrderId,80) || (order.side!=='BUY' && order.side!=='SELL') ||
      !positive(order.units) || !positive(order.entry!) || !positive(order.exit!) ||
      !nonnegative(order.commissionPerUnitSide) || !nonnegative(order.costs!) ||
      !Number.isFinite(order.pnl) ||
      !validTime(order.submittedAt) || !validTime(order.expiresAt) ||
      order.expiresAt<=order.submittedAt ||
      !validTime(order.entryObservedAt!) || !validTime(order.entryReceivedAt!) ||
      !validTime(order.exitObservedAt!) || !validTime(order.exitReceivedAt!) ||
      order.entryObservedAt!<=order.submittedAt ||
      order.entryReceivedAt!<order.entryObservedAt! ||
      order.entryReceivedAt!>=order.expiresAt ||
      order.exitObservedAt!<=order.entryObservedAt! ||
      order.exitReceivedAt!<order.exitObservedAt! ||
      order.exitReceivedAt!<order.entryReceivedAt! ||
      asOf<order.exitReceivedAt!) {
    throw Error('A closed, chronologically valid, source-identified paper order and settlement cutoff are required');
  }
  // Do not trust caller-supplied commission or net P&L in a detached saved
  // order. Both must reconcile with the recorded per-side fee schedule.
  const expectedCosts=2*order.commissionPerUnitSide*order.units;
  const gross=(order.side==='BUY' ? order.exit!-order.entry! : order.entry!-order.exit!)*order.units*identity.pointValue;
  const expected=gross-expectedCosts;
  if (!Number.isFinite(expectedCosts) || !Number.isFinite(gross) || !Number.isFinite(expected) ||
      !sameAmount(order.costs!,expectedCosts) || !sameAmount(order.pnl!,expected)) {
    throw Error('Paper order price, multiplier, commission and P&L do not reconcile');
  }
  const totals:Record<PaperCashflowKind,number>={OVERNIGHT_FINANCING:0,BORROW_FEE:0,FX_CONVERSION:0,BROKER_ADJUSTMENT:0};
  const seen=new Map<string,PaperCashflow>();
  for (const c of cashflows) {
    if (!validText(c.id,80) || !validText(c.reference,200) || c.orderId!==order.clientOrderId ||
        c.instrument!==identity.instrument || c.provider!==identity.provider || c.venue!==identity.venue ||
        !kinds.includes(c.kind) || !validTime(c.at) || c.at<order.entryReceivedAt! || c.at>asOf ||
        !Number.isFinite(c.amountCurrency)) throw Error('Invalid, unprovenanced or future paper cashflow');
    const prior=seen.get(c.id);
    if (prior) {
      if (Object.keys(prior).some(k=>prior[k as keyof PaperCashflow]!==c[k as keyof PaperCashflow])) {
        throw Error('Conflicting duplicate paper cashflow ID');
      }
      continue;
    }
    seen.set(c.id,{...c});
    totals[c.kind]+=c.amountCurrency;
    if (!Number.isFinite(totals[c.kind])) throw Error('Cashflow total overflow');
  }
  const adjusted=Object.values(totals).reduce((sum,value)=>sum+value,order.pnl!);
  if (!Number.isFinite(adjusted)) throw Error('Adjusted paper P&L overflow');
  return {orderId:order.clientOrderId,asOf,basePaperPnlCurrency:order.pnl!,
    cashflowCurrency:Object.freeze({...totals}),knownCashflowAdjustedPnlCurrency:adjusted,
    acceptedCashflows:seen.size,coverage:'PARTIAL_UNVERIFIED'};
}
