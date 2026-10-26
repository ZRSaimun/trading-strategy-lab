/** Offline NETTING-only reachability envelope from self-declared demo order events.
 * An envelope is NOT an authenticated position, executable risk limit, or permission.
 */
import {auditDeclaredDemoStatementPopulation} from './demo-statement-population-audit.ts';
import type {DemoStatementOrder,DemoStatementPopulationManifest} from './demo-statement-population-audit.ts';
import type {DemoLifecycleScope} from './demo-order-lifecycle-audit.ts';

export type DeclaredNettingPolicy = Readonly<{
  positionMode:'NETTING';
  /** Signed starting inventory, caller-declared, not broker authenticated. */
  startingNetContracts:number;
  /** Absolute inventory threshold for offline comparison only. */
  maxAbsContracts:number;
}>;
export type DeclaredNettingEnvelope = Readonly<{
  coverage:'SELF_DECLARED_DEMO_NETTING_ONLY';
  status:'DECLARED_POPULATION_UNVERIFIABLE'|'DECLARED_CAP_EXCEEDED'|
    'WITHIN_DECLARED_CAP_UNVERIFIED';
  statementPopulation:'DECLARED_POPULATION_MATCH_UNVERIFIED'|'DECLARED_POPULATION_MISMATCH';
  startingNetContracts:number;
  grossBuyFilledContracts:number; grossSellFilledContracts:number;
  netFilledPositionContracts:number;
  pendingBuyContracts:number; pendingSellContracts:number;
  /** Reachable signed net positions if all pending orders fill on either side. */
  minimumReachableNetContracts:number; maximumReachableNetContracts:number;
  worstCaseAbsoluteContracts:number; maxAbsContracts:number;
  cancelPendingOrders:number; submittedUnacknowledgedOrders:number;
  mayExecuteOrder:false; warnings:readonly string[];
}>;
const MAX=1_000_000_000;
function exact(value:unknown,keys:readonly string[],label:string):void {
  if(!value||typeof value!=='object'||Array.isArray(value)||
    Object.keys(value).length!==keys.length||
    Object.keys(value).some(key=>!keys.includes(key)))
    throw Error('Invalid '+label+' schema');
}
function integer(value:unknown):value is number {
  return typeof value==='number'&&Number.isSafeInteger(value)&&Math.abs(value)<=MAX;
}
/** Computes a conservative as-of envelope; it never treats cancel requests,
 * an expired clock without an EXPIRED event, or absent ACKs as canceled orders.
 * Only NETTING semantics are modeled. Hedging, cross-instrument netting, broker
 * risk reservations and unobserved orders are explicitly out of scope.
 */
export function reviewDeclaredDemoNettingEnvelope(
  scope:DemoLifecycleScope,manifest:DemoStatementPopulationManifest,
  orders:readonly DemoStatementOrder[],policy:DeclaredNettingPolicy
):DeclaredNettingEnvelope {
  exact(policy,['positionMode','startingNetContracts','maxAbsContracts'],'netting policy');
  if(policy.positionMode!=='NETTING'||!integer(policy.startingNetContracts)||
    !integer(policy.maxAbsContracts)||policy.maxAbsContracts<1)
    throw Error('Unsupported position mode or invalid declared contract cap');
  // Validates every source-bound lifecycle, unique order/event/fill identities,
  // quote ages and statement population before deriving any exposure figures.
  const population=auditDeclaredDemoStatementPopulation(scope,manifest,orders);
  const byId=new Map(population.orderReviews.map(review=>[review.clientOrderId,review]));
  let grossBuy=0,grossSell=0,pendingBuy=0,pendingSell=0;
  let cancelPending=0,unacknowledged=0;
  for(const order of orders){
    const review=byId.get(order.intent.clientOrderId);
    if(!review)throw Error('Missing validated order review');
    const filled=review.filledContracts;
    if(order.intent.side==='BUY')grossBuy+=filled;
    else grossSell+=filled;
    if(!review.terminal){
      // CANCEL_PENDING is still fillable until an explicit terminal event.
      if(order.intent.side==='BUY')pendingBuy+=review.remainingContracts;
      else pendingSell+=review.remainingContracts;
      if(review.status==='CANCEL_PENDING')cancelPending++;
      if(review.status==='SUBMITTED')unacknowledged++;
    }
  }
  const net=policy.startingNetContracts+grossBuy-grossSell;
  const minimum=net-pendingSell,maximum=net+pendingBuy;
  const worst=Math.max(Math.abs(minimum),Math.abs(maximum));
  // Bounded individual contracts and <=500 orders keep all sums safe.
  if(![grossBuy,grossSell,pendingBuy,pendingSell,net,minimum,maximum,worst]
    .every(Number.isSafeInteger))throw Error('Unsafe aggregate contract count');
  const status=population.status==='DECLARED_POPULATION_MISMATCH'?
    'DECLARED_POPULATION_UNVERIFIABLE':worst>policy.maxAbsContracts?
    'DECLARED_CAP_EXCEEDED':'WITHIN_DECLARED_CAP_UNVERIFIED';
  return {coverage:'SELF_DECLARED_DEMO_NETTING_ONLY',status,
    statementPopulation:population.status,startingNetContracts:policy.startingNetContracts,
    grossBuyFilledContracts:grossBuy,grossSellFilledContracts:grossSell,
    netFilledPositionContracts:net,pendingBuyContracts:pendingBuy,
    pendingSellContracts:pendingSell,minimumReachableNetContracts:minimum,
    maximumReachableNetContracts:maximum,worstCaseAbsoluteContracts:worst,
    maxAbsContracts:policy.maxAbsContracts,cancelPendingOrders:cancelPending,
    submittedUnacknowledgedOrders:unacknowledged,mayExecuteOrder:false,
    warnings:[
      'Source, account mode, starting inventory, manifest, order events and hashes are caller-declared, not authenticated broker evidence.',
      'A matching declared manifest cannot prove completeness; unknown external orders, fills, and positions are not included.',
      'Outstanding orders, including cancellation requests and unacknowledged submissions, remain potentially fillable until explicit terminal evidence.',
      'The envelope assumes NETTING for one instrument and does not model hedging, margin, liquidity, order sequencing, financing, cash P&L or actual broker risk caps.',
      'A within-cap result is an offline comparison only, never an execution approval or evidence of profitable trading.'
    ]};
}
