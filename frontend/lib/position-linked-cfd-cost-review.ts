/** Opt-in, offline position-linkage gate for declared CFD cost research.
 * Self-declared source digests and links are NOT broker authentication.
 * This module has no network access, orders, broker adapter or P&L.
 */
import {reviewDeclaredCfdCostEnvelope, type CostStress, type DeclaredCostEnvelope}
  from './declared-cfd-cost-envelope.ts';
import type {QuoteExecutionScope, DeclaredOrder, DeclaredQuote, DeclaredFill}
  from './declared-quote-execution-audit.ts';
import type {FinancingScope, FinancingReceipt}
  from './declared-cfd-financing-audit.ts';

export type OrderPositionLink = Readonly<{
  orderId:string; positionId:string; recordedAt:number;
}>;
export type FillPositionLink = Readonly<{
  fillId:string; orderId:string; positionId:string; recordedAt:number;
}>;
export type DeclaredPositionLinkage = Readonly<{
  provider:string; venue:string; instrument:string; accountAlias:string;
  positionId:string; quoteBatchSha256:string; financingStatementSha256:string;
  executionStatementSha256:string; evidenceSource:'PAPER_LEDGER'|'BROKER_EXPORT';
  asOf:number;
  orderLinks:readonly OrderPositionLink[];
  fillLinks:readonly FillPositionLink[];
}>;
export type PositionLinkedCostReview = Readonly<{
  linkageStatus:'COMPLETE_SELF_DECLARED_POSITION_LINKAGE';
  evidenceSource:'PAPER_LEDGER'|'BROKER_EXPORT';
  executionStatementSha256:string;
  positionId:string;
  cost:DeclaredCostEnvelope;
  warnings:readonly string[];
}>;
const ID=/^[A-Za-z0-9._:-]{1,120}$/;
const SHA=/^[a-f0-9]{64}$/;
const TIME=(n:unknown):n is number=>typeof n==='number'&&Number.isSafeInteger(n)&&n>=0;
function exact(x:unknown, keys:readonly string[], label:string):void {
  if(!x||typeof x!=='object'||Array.isArray(x)||Object.keys(x).length!==keys.length||
    Object.keys(x).some(k=>!keys.includes(k))) throw Error('Invalid '+label+' schema');
}
/** All orders and fills must have a one-to-one declared position association.
 * No unlinked or foreign records may silently enter the cost population.
 * A supplied digest is only an identifier; no source bytes or signatures are verified.
 */
export function reviewPositionLinkedDeclaredCfdCosts(
  quoteScope:QuoteExecutionScope, orders:readonly DeclaredOrder[],
  quotes:readonly DeclaredQuote[], fills:readonly DeclaredFill[],
  financingScope:FinancingScope, receipts:readonly FinancingReceipt[],
  linkage:DeclaredPositionLinkage, budget:string, stresses:readonly CostStress[]
):PositionLinkedCostReview {
  exact(linkage,['provider','venue','instrument','accountAlias','positionId',
    'quoteBatchSha256','financingStatementSha256','executionStatementSha256',
    'evidenceSource','asOf','orderLinks','fillLinks'],'position linkage');
  if(![linkage.provider,linkage.venue,linkage.instrument,linkage.accountAlias,
    linkage.positionId].every(x=>typeof x==='string'&&ID.test(x))||
    ![linkage.quoteBatchSha256,linkage.financingStatementSha256,
      linkage.executionStatementSha256].every(x=>typeof x==='string'&&SHA.test(x))||
    !['PAPER_LEDGER','BROKER_EXPORT'].includes(linkage.evidenceSource)||
    !TIME(linkage.asOf)||linkage.asOf>quoteScope.asOf||
    linkage.asOf>financingScope.asOf)
    throw Error('Invalid declared position-linkage provenance or clock');
  if(linkage.provider!==quoteScope.provider||linkage.provider!==financingScope.provider||
    linkage.venue!==quoteScope.venue||linkage.venue!==financingScope.venue||
    linkage.instrument!==quoteScope.instrument||linkage.instrument!==financingScope.instrument||
    linkage.accountAlias!==quoteScope.accountAlias||
    linkage.accountAlias!==financingScope.accountAlias||
    linkage.positionId!==financingScope.positionId||
    linkage.quoteBatchSha256!==quoteScope.quoteBatchSha256||
    linkage.financingStatementSha256!==financingScope.statementSha256)
    throw Error('Position linkage mismatches CFD cost source or position identity');
  if(!Array.isArray(orders)||!Array.isArray(fills)||!Array.isArray(linkage.orderLinks)||
    !Array.isArray(linkage.fillLinks)||orders.length>5000||fills.length>5000||
    linkage.orderLinks.length!==orders.length||linkage.fillLinks.length!==fills.length)
    throw Error('Incomplete or unbounded position-linkage coverage');
  const orderMap=new Map(orders.map(o=>[o.orderId,o]));
  const fillMap=new Map(fills.map(f=>[f.fillId,f]));
  if(orderMap.size!==orders.length||fillMap.size!==fills.length)
    throw Error('Duplicate declared order or fill IDs');
  const orderIds=new Set<string>();
  for(const link of linkage.orderLinks) {
    exact(link,['orderId','positionId','recordedAt'],'order position link');
    const order=orderMap.get(link.orderId);
    if(!ID.test(link.orderId)||orderIds.has(link.orderId)||!order||
      link.positionId!==linkage.positionId||!TIME(link.recordedAt)||
      link.recordedAt<order.submittedAt||link.recordedAt>linkage.asOf)
      throw Error('Duplicate, foreign, future or invalid order-position link');
    orderIds.add(link.orderId);
  }
  const fillIds=new Set<string>();
  for(const link of linkage.fillLinks) {
    exact(link,['fillId','orderId','positionId','recordedAt'],'fill position link');
    const fill=fillMap.get(link.fillId);
    if(!ID.test(link.fillId)||fillIds.has(link.fillId)||!fill||
      link.orderId!==fill.orderId||!orderIds.has(link.orderId)||
      link.positionId!==linkage.positionId||!TIME(link.recordedAt)||
      link.recordedAt<fill.filledAt||link.recordedAt>linkage.asOf)
      throw Error('Duplicate, foreign, future or invalid fill-position link');
    fillIds.add(link.fillId);
  }
  // The original quote, fill, financing and temporal audits still run in full.
  const cost=reviewDeclaredCfdCostEnvelope(quoteScope,orders,quotes,fills,
    financingScope,receipts,budget,stresses);
  return {
    linkageStatus:'COMPLETE_SELF_DECLARED_POSITION_LINKAGE',
    evidenceSource:linkage.evidenceSource,
    executionStatementSha256:linkage.executionStatementSha256,
    positionId:linkage.positionId,cost,
    warnings:[
      'Every declared order and fill is linked to one declared position; this does not prove the linkage is true.',
      'Statement SHA-256 strings and evidenceSource are caller declarations, not verified source bytes or broker signatures.',
      'Link records can be backfilled after outcomes; independent immutable preregistration and complete broker exports are still required.',
      'No real or demo orders, P&L, executable liquidity, margin, risk cap, or profitable edge is established.'
    ]
  };
}
