/**
 * Offline as-of valuation freshness gate for a caller-supplied paper journal.
 * It NEVER authenticates bid/ask quotes, persists records, contacts a broker,
 * authorizes order previews, or claims executable/live market valuation.
 */
import {
  replayDisconnectedPaperLedger,
  type PaperEvent, type PaperPolicy, type PaperSource,
} from './disconnected-paper-ledger.ts';

export type PaperValuationFreshness = {
  mode:'UNVERIFIED_LOCAL_RESEARCH';live:false;persisted:false;
  quoteAuthenticated:false;executableQuoteAvailable:false;
  orderPreviewEnabled:false;ordersSubmitted:0;
  status:'FLAT_REALIZED_ONLY'|'RECENT_UNAUTHENTICATED_MARK'|'STALE_OPEN_MARK';
  asOf:number;lastQuoteAt:number|null;quoteAgeSeconds:number|null;
  maxValuationAgeSeconds:number;positionOpen:boolean;
  realizedNet:number;lastObservedEquity:number;
  lastObservedUnrealizedNet:number;observedMaxDrawdownPct:number;
  asOfResearchEquity:number|null;asOfResearchUnrealizedNet:number|null;
};
const epoch=(n:number)=>Number.isSafeInteger(n)&&n>=0;
/**
 * Caller controls `asOf` and every event timestamp: this is an offline
 * rehearsal, not a trusted server receipt clock. An open position with a stale
 * quote MUST NOT be presented with a current mark or equity. Flat portfolios
 * need no quote to calculate their cash-only realized balance.
 */
export function auditPaperValuationFreshness(
  events:readonly PaperEvent[],source:PaperSource,policy:PaperPolicy,
  asOf:number,maxValuationAgeSeconds=120,
):PaperValuationFreshness{
  if(!epoch(asOf)||!Number.isSafeInteger(maxValuationAgeSeconds)||
     maxValuationAgeSeconds<0||maxValuationAgeSeconds>3600||
     !Array.isArray(events)||events.some(e=>!e||!epoch(e.at)||e.at>asOf))
    throw Error('Invalid or future-dated as-of paper valuation');
  // Revalidate all sequence, price, source, order, fee and cash constraints;
  // never trust a caller-supplied cached snapshot.
  const replay=replayDisconnectedPaperLedger(events,source,policy);
  const lastQuote=[...events].reverse().find(e=>e.kind==='QUOTE');
  const lastQuoteAt=lastQuote?.at??null;
  const quoteAgeSeconds=lastQuoteAt===null?null:asOf-lastQuoteAt;
  const positionOpen=replay.openPosition!==null;
  const fresh=quoteAgeSeconds!==null&&quoteAgeSeconds<=maxValuationAgeSeconds;
  const status:PaperValuationFreshness['status']=!positionOpen?
    'FLAT_REALIZED_ONLY':fresh?'RECENT_UNAUTHENTICATED_MARK':'STALE_OPEN_MARK';
  const base={mode:'UNVERIFIED_LOCAL_RESEARCH' as const,live:false as const,
    persisted:false as const,quoteAuthenticated:false as const,
    executableQuoteAvailable:false as const,orderPreviewEnabled:false as const,
    ordersSubmitted:0 as const,status,asOf,lastQuoteAt,quoteAgeSeconds,
    maxValuationAgeSeconds,positionOpen,realizedNet:replay.realizedNet,
    lastObservedEquity:replay.equity,
    lastObservedUnrealizedNet:replay.unrealizedNet,
    observedMaxDrawdownPct:replay.maxDrawdownPct};
  return {...base,
    asOfResearchEquity:status==='STALE_OPEN_MARK'?null:replay.equity,
    asOfResearchUnrealizedNet:status==='STALE_OPEN_MARK'?null:replay.unrealizedNet};
}
