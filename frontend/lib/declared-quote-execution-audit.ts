/** Disconnected, self-declared CFD quote/fill cost reconciliation for research.
 * No broker connection, orders, price feed, persistence or strategy P&L.
 */
export type QuoteExecutionScope = Readonly<{
  provider: string; venue: string; instrument: string; accountAlias: string;
  quoteStreamId: string; quoteCurrency: string; quoteBatchSha256: string;
  asOf: number; maxQuoteAgeMs: number;
  /** Explicit cash in quoteCurrency per 1.0 price move per contract. NOT inferred from symbol. */
  cashPerPricePointPerContract: string;
}>;
export type DeclaredOrder = Readonly<{
  orderId: string; side: 'BUY'|'SELL'; requestedContracts: number; submittedAt: number;
}>;
export type DeclaredQuote = Readonly<{
  quoteId: string; provider: string; venue: string; instrument: string;
  quoteStreamId: string; quoteBatchSha256: string;
  observedAt: number; bid: string; ask: string;
}>;
export type DeclaredFill = Readonly<{
  fillId: string; orderId: string; provider: string; venue: string;
  instrument: string; accountAlias: string; quoteId: string;
  filledAt: number; filledContracts: number; price: string; commissionCurrency: string;
}>;
export type FillFriction = Readonly<{
  fillId: string; orderId: string; quoteId: string; quoteAgeMs: number;
  /** One-sided spread cost relative to quote midpoint, not a round-trip spread. */
  halfSpreadCurrency: string;
  /** Signed slippage versus ask for buys and bid for sells; negative = improvement. */
  slippageCurrency: string;
  commissionCurrency: string;
  totalFrictionCurrency: string;
}>;
export type QuoteExecutionAudit = Readonly<{
  status: 'COMPLETE_DECLARED'|'PARTIAL_DECLARED'|'NO_DECLARED_FILLS';
  coverage: 'SELF_DECLARED_QUOTE_AND_FILL_EVIDENCE_ONLY';
  requestedContracts: number; filledContracts: number;
  unfilledOrderIds: readonly string[];
  fillFriction: readonly FillFriction[];
  /** Null for incomplete orders or absent fills; never imply unfilled orders were free. */
  completeFrictionCurrency: string|null;
  warnings: readonly string[];
}>;
const SHA = /^[a-f0-9]{64}$/;
const ID = /^[A-Za-z0-9._:-]{1,120}$/;
const CUR = /^[A-Z]{3}$/;
const SCOPE_KEYS = ['provider','venue','instrument','accountAlias','quoteStreamId',
  'quoteCurrency','quoteBatchSha256','asOf','maxQuoteAgeMs','cashPerPricePointPerContract'];
const ORDER_KEYS = ['orderId','side','requestedContracts','submittedAt'];
const QUOTE_KEYS = ['quoteId','provider','venue','instrument','quoteStreamId',
  'quoteBatchSha256','observedAt','bid','ask'];
const FILL_KEYS = ['fillId','orderId','provider','venue','instrument','accountAlias',
  'quoteId','filledAt','filledContracts','price','commissionCurrency'];
const TIME = (n:unknown):n is number => typeof n==='number'&&Number.isSafeInteger(n)&&n>=0;
const CONTRACTS = (n:unknown):n is number => typeof n==='number'&&Number.isSafeInteger(n)&&n>0&&n<=1_000_000;
function exact(x:unknown, keys:readonly string[], label:string):void {
  if(!x||typeof x!=='object'||Array.isArray(x)||Object.keys(x).length!==keys.length||
     Object.keys(x).some(k=>!keys.includes(k))) throw Error('Invalid '+label+' schema');
}
/** Fixed-point price and multiplier, six decimal places, no JS float arithmetic. */
function decimal6(x:unknown, label:string, allowZero=false):bigint {
  if(typeof x!=='string'||! /^(?:0|[1-9][0-9]{0,7})(?:\.[0-9]{1,6})?$/.test(x))
    throw Error('Invalid '+label+' decimal');
  const [whole,frac='']=x.split('.');
  const value=BigInt(whole)*1_000_000n+BigInt(frac.padEnd(6,'0')||'0');
  if(!allowZero&&value===0n) throw Error('Zero '+label+' not permitted');
  return value;
}
function cents(x:unknown):bigint {
  if(typeof x!=='string'||! /^(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,2})?$/.test(x))
    throw Error('Invalid commission decimal');
  const [whole,frac='']=x.split('.');
  return BigInt(whole)*100n+BigInt(frac.padEnd(2,'0')||'0');
}
/** Costs use exact 13-decimal cash units, retaining half-micro-price spread precision. */
function money13(units:bigint):string {
  const negative=units<0n; const n=negative?-units:units;
  return (negative?'-':'')+(n/10_000_000_000_000n)+'.'+String(n%10_000_000_000_000n).padStart(13,'0');
}
const WARNINGS = [
  'Quotes, timestamps, contract multiplier and fill records are caller-declared, not authenticated or executable broker evidence.',
  'No independent proof of full quote-stream coverage, best execution, financing, FX, margin, rejects, cancellations or market-session validity.',
  'Half-spread is one-sided relative to the declared quote midpoint; do not double-count a separate full-spread cost.',
  'Partial/unfilled orders withhold complete friction; this audit does not measure strategy returns or demonstrate profitability.'
] as const;
/** Strict reconciliation of a bounded set of declared market orders, quote snapshots and fills.
 * Quotes must be bound to fills; unmatched/unused evidence and inconsistent identities fail closed.
 */
export function auditDeclaredQuoteExecutions(
  scope:QuoteExecutionScope,
  orders:readonly DeclaredOrder[], quotes:readonly DeclaredQuote[], fills:readonly DeclaredFill[]
):QuoteExecutionAudit {
  exact(scope,SCOPE_KEYS,'quote execution scope');
  if(![scope.provider,scope.venue,scope.instrument,scope.accountAlias,scope.quoteStreamId].every(x=>
    typeof x==='string'&&ID.test(x))||!CUR.test(scope.quoteCurrency)||
    !SHA.test(scope.quoteBatchSha256)||!TIME(scope.asOf)||
    !TIME(scope.maxQuoteAgeMs)||scope.maxQuoteAgeMs===0||scope.maxQuoteAgeMs>300_000)
    throw Error('Invalid quote scope identity or freshness bounds');
  const multiplier=decimal6(scope.cashPerPricePointPerContract,'cash multiplier');
  if(!Array.isArray(orders)||!Array.isArray(quotes)||!Array.isArray(fills)||
    orders.length>5000||quotes.length>5000||fills.length>5000)
    throw Error('Unbounded quote audit records');
  const orderMap=new Map<string,DeclaredOrder>();
  const filledByOrder=new Map<string,number>();
  let requested=0,filled=0;
  for(const o of orders){
    exact(o,ORDER_KEYS,'declared order');
    if(!ID.test(o.orderId)||orderMap.has(o.orderId)||!['BUY','SELL'].includes(o.side)||
      !CONTRACTS(o.requestedContracts)||!TIME(o.submittedAt)||o.submittedAt>scope.asOf)
      throw Error('Invalid, duplicate or future declared order');
    orderMap.set(o.orderId,o);requested+=o.requestedContracts;
  }
  const quoteMap=new Map<string,DeclaredQuote>();
  for(const q of quotes){
    exact(q,QUOTE_KEYS,'declared quote');
    if(!ID.test(q.quoteId)||quoteMap.has(q.quoteId)||q.provider!==scope.provider||
      q.venue!==scope.venue||q.instrument!==scope.instrument||
      q.quoteStreamId!==scope.quoteStreamId||q.quoteBatchSha256!==scope.quoteBatchSha256||
      !TIME(q.observedAt)||q.observedAt>scope.asOf)
      throw Error('Invalid, duplicate, future or cross-source quote');
    const bid=decimal6(q.bid,'bid'),ask=decimal6(q.ask,'ask');
    if(ask<bid) throw Error('Crossed bid/ask quote');
    quoteMap.set(q.quoteId,q);
  }
  const fillIds=new Set<string>(),usedQuotes=new Set<string>();
  const breakdown:FillFriction[]=[];
  let total=0n;
  for(const f of fills){
    exact(f,FILL_KEYS,'declared fill');
    const o=orderMap.get(f.orderId),q=quoteMap.get(f.quoteId);
    if(!ID.test(f.fillId)||fillIds.has(f.fillId)||!o||!q||
      f.provider!==scope.provider||f.venue!==scope.venue||
      f.instrument!==scope.instrument||f.accountAlias!==scope.accountAlias||
      !TIME(f.filledAt)||f.filledAt>scope.asOf||f.filledAt<o.submittedAt||
      f.filledAt<q.observedAt||f.filledAt-q.observedAt>scope.maxQuoteAgeMs||
      !CONTRACTS(f.filledContracts))
      throw Error('Invalid, duplicate, stale, future or cross-source fill');
    const cumulative=(filledByOrder.get(o.orderId)||0)+f.filledContracts;
    if(cumulative>o.requestedContracts) throw Error('Fill quantity exceeds declared order');
    filledByOrder.set(o.orderId,cumulative);
    const bid=decimal6(q.bid,'bid'),ask=decimal6(q.ask,'ask');
    const price=decimal6(f.price,'fill price'),commission=cents(f.commissionCurrency);
    // 13-digit cash precision: (ask-bid)/2 * multiplier * contracts.
    const halfSpread=(ask-bid)*multiplier*BigInt(f.filledContracts)*5n;
    // Signed cost relative to executable side of declared quote, not the midpoint.
    const slipDelta=o.side==='BUY'?price-ask:bid-price;
    const slippage=slipDelta*multiplier*BigInt(f.filledContracts)*10n;
    const commissionUnits=commission*100_000_000_000n;
    const friction=halfSpread+slippage+commissionUnits;
    breakdown.push({fillId:f.fillId,orderId:o.orderId,quoteId:q.quoteId,
      quoteAgeMs:f.filledAt-q.observedAt,halfSpreadCurrency:money13(halfSpread),
      slippageCurrency:money13(slippage),commissionCurrency:money13(commissionUnits),
      totalFrictionCurrency:money13(friction)});
    total+=friction;filled+=f.filledContracts;fillIds.add(f.fillId);usedQuotes.add(f.quoteId);
  }
  if([...quoteMap.keys()].some(id=>!usedQuotes.has(id)))
    throw Error('Unmatched declared quote without a fill');
  const unfilled=[...orderMap.values()].filter(o=>filledByOrder.get(o.orderId)!==o.requestedContracts)
    .map(o=>o.orderId);
  const status=fills.length===0?'NO_DECLARED_FILLS':unfilled.length?'PARTIAL_DECLARED':'COMPLETE_DECLARED';
  return {status,coverage:'SELF_DECLARED_QUOTE_AND_FILL_EVIDENCE_ONLY',
    requestedContracts:requested,filledContracts:filled,unfilledOrderIds:unfilled,
    fillFriction:breakdown,completeFrictionCurrency:status==='COMPLETE_DECLARED'&&orders.length>0?
      money13(total):null,warnings:WARNINGS};
}
