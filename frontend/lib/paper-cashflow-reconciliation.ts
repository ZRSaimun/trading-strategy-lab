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

/** The result is NOT broker net P&L unless every charge and source is independently reconciled. */
export function reconcilePaperCashflows(
  identity:PaperIdentity,order:PaperOrder,asOf:number,cashflows:readonly PaperCashflow[]
):PaperCashflowReconciliation {
  if (!validTime(asOf) || identity.priceSide!=='bid-ask' || !Number.isFinite(identity.pointValue) || identity.pointValue<=0 ||
      !validText(identity.instrument,160) || !validText(identity.provider,160) || !validText(identity.venue,160) ||
      order.status!=='CLOSED' || order.instrument!==identity.instrument ||
      !validTime(order.entryReceivedAt!) || !validTime(order.exitReceivedAt!) ||
      order.exitReceivedAt!<order.entryReceivedAt! || asOf<order.exitReceivedAt! ||
      !Number.isFinite(order.entry) || !Number.isFinite(order.exit) ||
      !Number.isFinite(order.pnl) || !Number.isFinite(order.costs) ||
      !Number.isFinite(order.units) || order.units<=0 || order.costs!<0) {
    throw Error('A closed, source-identified paper order and settlement cutoff are required');
  }
  const gross=(order.side==='BUY' ? order.exit!-order.entry! : order.entry!-order.exit!)*order.units*identity.pointValue;
  const expected=gross-order.costs!;
  if (!Number.isFinite(expected) || Math.abs(expected-order.pnl!)>Math.max(1e-8,Math.abs(expected)*1e-9)) {
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
