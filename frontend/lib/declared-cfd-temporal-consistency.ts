/** Offline cross-audit time-window guard. This does not prove order-to-position
 * identity, broker authenticity, or completeness of declared financing.
 */
export type QuoteEvidenceClock = Readonly<{asOf:number}>;
export type FinancingEvidenceClock = Readonly<{openedAt:number;closedAt:number;asOf:number}>;
export type SubmittedOrderClock = Readonly<{submittedAt:number}>;
export type FilledOrderClock = Readonly<{filledAt:number}>;

/** Prevent combining fills from outside the declared financed position window.
 * A submitted order may precede the position opening; only its fill must occur
 * during the position window. Both upstream audits must still run first.
 */
export function assertDeclaredCfdTemporalConsistency(
  quoteScope:QuoteEvidenceClock, orders:readonly SubmittedOrderClock[],
  fills:readonly FilledOrderClock[], financingScope:FinancingEvidenceClock
):void {
  if(quoteScope.asOf<financingScope.closedAt)
    throw Error('Quote evidence snapshot predates the declared financing position close');
  if(orders.some(o=>o.submittedAt>financingScope.closedAt))
    throw Error('Declared order submitted after the financing position close');
  if(fills.some(f=>f.filledAt<financingScope.openedAt||f.filledAt>financingScope.closedAt))
    throw Error('Declared fill outside the financing position interval');
}
