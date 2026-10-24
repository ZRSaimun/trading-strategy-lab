/** Deterministic in-memory research-only bid/ask execution simulation.
 * No broker, database, network, order routing or credentials.
 */
export type PaperSide = 'BUY' | 'SELL';
export type PaperStatus = 'PENDING' | 'OPEN' | 'CLOSED' | 'CANCELED' | 'EXPIRED' | 'REJECTED';
export type PaperIdentity = Readonly<{
  instrument: string; provider: string; venue: string; priceSide: 'bid-ask'; pointValue: number;
}>;
export type PaperQuote = Readonly<{
  instrument: string; provider: string; venue: string;
  observedAt: number; receivedAt: number; bid: number; ask: number;
}>;
export type PaperRequest = Readonly<{
  clientOrderId: string; instrument: string; side: PaperSide; units: number;
  submittedAt: number; expiresAt: number; stop: number; target: number;
  maxSpread: number; maxQuoteAgeSeconds: number; maxStopRiskCurrency: number;
  adverseSlippagePerSide: number; commissionPerUnitSide: number;
}>;
export type PaperOrder = PaperRequest & {
  status: PaperStatus; reason?: string;
  entry?: number; entryObservedAt?: number; entryReceivedAt?: number;
  exit?: number; exitObservedAt?: number; exitReceivedAt?: number;
  pnl?: number; costs?: number; initialStopRisk?: number;
};
export type PaperEvent = Readonly<{orderId: string; status: PaperStatus; reason: string; at: number}>;
const finite = (x: number) => Number.isFinite(x);
const timestamp = (x: number) => Number.isSafeInteger(x) && x >= 0;
const positive = (x: number) => finite(x) && x > 0;
const nonnegative = (x: number) => finite(x) && x >= 0;
const validId = (x: string) => typeof x === 'string' && /^[A-Za-z0-9_-]{1,80}$/.test(x);

/** One exact instrument/source per ledger. Quotes are externally supplied, never invented. */
export class PaperExecutionLedger {
  private readonly requests = new Map<string, PaperRequest>();
  private readonly orders = new Map<string, PaperOrder>();
  private lastObservedAt = -1;
  private lastReceivedAt = -1;
  private readonly events: PaperEvent[] = [];
  readonly identity: PaperIdentity;
  constructor(identity: PaperIdentity) {
    this.identity = Object.freeze({...identity});
    if (!identity.instrument || !identity.provider || !identity.venue ||
        identity.priceSide !== 'bid-ask' || !positive(identity.pointValue)) {
      throw Error('Exact bid/ask source identity and positive point value required');
    }
  }
  /** Duplicate client IDs with identical request bodies are idempotent. */
  submit(request: PaperRequest): PaperOrder {
    const existing = this.requests.get(request.clientOrderId);
    if (existing) {
      if (JSON.stringify(existing) !== JSON.stringify(request)) throw Error('Conflicting duplicate client order ID');
      return this.get(request.clientOrderId)!;
    }
    if (!validId(request.clientOrderId) || request.instrument !== this.identity.instrument ||
        (request.side !== 'BUY' && request.side !== 'SELL') || !positive(request.units) ||
        !timestamp(request.submittedAt) || !timestamp(request.expiresAt) ||
        request.expiresAt <= request.submittedAt || request.submittedAt < this.lastReceivedAt ||
        !positive(request.stop) || !positive(request.target) ||
        !nonnegative(request.maxSpread) || !nonnegative(request.maxQuoteAgeSeconds) ||
        !positive(request.maxStopRiskCurrency) || !nonnegative(request.adverseSlippagePerSide) ||
        !nonnegative(request.commissionPerUnitSide)) throw Error('Invalid paper order or retroactive submission');
    if ([...this.orders.values()].some(o => o.status === 'PENDING' || o.status === 'OPEN')) {
      throw Error('One pending/open position per source ledger; no overlapping paper orders');
    }
    const copy = {...request};
    this.requests.set(copy.clientOrderId, copy);
    this.orders.set(copy.clientOrderId, {...copy, status:'PENDING'});
    return this.get(copy.clientOrderId)!;
  }
  /** Cancellation is a simulated local transition, not a broker request. */
  cancel(id: string, at: number): PaperOrder {
    const order = this.orders.get(id);
    if (!order) throw Error('Unknown paper order');
    if (!timestamp(at) || at < order.submittedAt || at < this.lastReceivedAt) throw Error('Retroactive cancellation');
    if (order.status !== 'PENDING') throw Error('Only pending paper orders can be canceled');
    order.status = 'CANCELED'; order.reason = 'Owner simulated cancellation';
    this.events.push({orderId:id,status:'CANCELED',reason:order.reason,at});
    return this.get(id)!;
  }
  /** Invalid, duplicated or out-of-order quote events are rejected without mutation. */
  onQuote(quote: PaperQuote): readonly PaperEvent[] {
    if (quote.instrument !== this.identity.instrument || quote.provider !== this.identity.provider ||
        quote.venue !== this.identity.venue) throw Error('Quote source identity mismatch');
    if (!timestamp(quote.observedAt) || !timestamp(quote.receivedAt) ||
        quote.observedAt > quote.receivedAt || quote.observedAt <= this.lastObservedAt ||
        quote.receivedAt < this.lastReceivedAt || !positive(quote.bid) ||
        !positive(quote.ask) || quote.ask < quote.bid) throw Error('Invalid, future or non-monotonic bid/ask quote');
    this.lastObservedAt = quote.observedAt;
    this.lastReceivedAt = quote.receivedAt;
    const changes: PaperEvent[] = [];
    const emit = (o: PaperOrder, reason: string) => {
      o.reason = reason;
      const event = {orderId:o.clientOrderId,status:o.status,reason,at:quote.receivedAt};
      this.events.push(event); changes.push(event);
    };
    for (const o of this.orders.values()) {
      if (o.status === 'PENDING') {
        if (quote.receivedAt >= o.expiresAt) {
          o.status = 'EXPIRED'; emit(o, 'Order expired before an eligible fresh quote'); continue;
        }
        // A quote already observed before the order cannot be used to fill it.
        if (quote.observedAt <= o.submittedAt || quote.receivedAt - quote.observedAt > o.maxQuoteAgeSeconds ||
            quote.ask - quote.bid > o.maxSpread) continue;
        const slip = o.adverseSlippagePerSide;
        const entry = o.side === 'BUY' ? quote.ask + slip : quote.bid - slip;
        if (!positive(entry) || (o.side === 'BUY' ? !(o.stop < entry && entry < o.target) : !(o.target < entry && entry < o.stop))) {
          o.status = 'REJECTED'; emit(o, 'Invalid bracket at executable quote'); continue;
        }
        const stopRisk = (Math.abs(entry - o.stop) + slip)*o.units*this.identity.pointValue +
          2*o.commissionPerUnitSide*o.units;
        if (!finite(stopRisk) || stopRisk > o.maxStopRiskCurrency) {
          o.status = 'REJECTED'; emit(o, 'Hypothetical stop loss exceeds user risk cap'); continue;
        }
        o.entry = entry; o.entryObservedAt = quote.observedAt; o.entryReceivedAt = quote.receivedAt;
        o.initialStopRisk = stopRisk; o.status = 'OPEN'; emit(o, 'Paper market entry at adverse bid/ask plus slippage');
      } else if (o.status === 'OPEN') {
        if (quote.observedAt <= o.entryObservedAt! || quote.receivedAt - quote.observedAt > o.maxQuoteAgeSeconds) continue;
        let exit: number | undefined; let reason = '';
        const slip = o.adverseSlippagePerSide;
        if (o.side === 'BUY') {
          if (quote.bid <= o.stop) {exit = Math.min(o.stop, quote.bid - slip); reason = 'Stop triggered: gap/slippage may exceed stop';}
          else if (quote.bid >= o.target) {exit = o.target; reason = 'Target: no favorable price improvement assumed';}
        } else {
          if (quote.ask >= o.stop) {exit = Math.max(o.stop, quote.ask + slip); reason = 'Stop triggered: gap/slippage may exceed stop';}
          else if (quote.ask <= o.target) {exit = o.target; reason = 'Target: no favorable price improvement assumed';}
        }
        if (exit === undefined) continue;
        const gross = (o.side === 'BUY' ? exit-o.entry! : o.entry!-exit)*o.units*this.identity.pointValue;
        const costs = 2*o.commissionPerUnitSide*o.units;
        o.exit = exit; o.exitObservedAt = quote.observedAt; o.exitReceivedAt = quote.receivedAt;
        o.costs = costs; o.pnl = gross - costs; o.status = 'CLOSED'; emit(o, reason);
      }
    }
    return changes;
  }
  get(id: string): PaperOrder | undefined {const o = this.orders.get(id); return o ? {...o} : undefined;}
  history(): readonly PaperEvent[] {return this.events.map(e=>({...e}));}
}
