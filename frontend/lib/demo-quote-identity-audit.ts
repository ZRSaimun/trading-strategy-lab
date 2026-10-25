/** Offline cross-order consistency of caller-declared demo quote identifiers.
 * A matching quote ID is NOT proof of an executable, authentic broker quote.
 * No broker calls, order routing, credentials, margin or P&L.
 */
import {auditDeclaredDemoStatementPopulation} from './demo-statement-population-audit.ts';
import type {DemoStatementOrder,DemoStatementPopulationManifest} from './demo-statement-population-audit.ts';
import type {DemoLifecycleScope} from './demo-order-lifecycle-audit.ts';

export type DemoQuoteIdentityReview = Readonly<{
  coverage:'SELF_DECLARED_DEMO_QUOTE_IDS_ONLY';
  status:'NO_DECLARED_FILLS'|'DECLARED_POPULATION_MISMATCH'|
    'CONFLICTING_DECLARED_QUOTE_ID'|'CONSISTENT_DECLARED_QUOTE_IDS_UNVERIFIED';
  statementPopulation:'DECLARED_POPULATION_MATCH_UNVERIFIED'|'DECLARED_POPULATION_MISMATCH';
  fillEvents:number;
  distinctQuoteIds:number;
  reusedQuoteIds:number;
  conflictingQuoteIds:readonly string[];
  conflicts:readonly Readonly<{
    quoteId:string; firstEventId:string; conflictingEventId:string;
  }>[];
  mayExecuteOrder:false;
  warnings:readonly string[];
}>;
type QuoteSnapshot = Readonly<{
  eventId:string; observedAt:number; bid:string; ask:string; batchSha256:string;
}>;
function canonicalSix(value:string):string {
  // The upstream lifecycle validator already enforces a strict positive
  // decimal with <=6 places. Normalize equivalent representations for identity.
  const [whole,fraction='']=value.split('.');
  return whole+'.'+fraction.padEnd(6,'0');
}
/** Revalidate full lifecycle and statement population first. An identical
 * quoteId reused in one declared quote batch must refer to identical quote
 * values and observed timestamp, even when fills belong to different orders.
 * Conflicts fail closed; no result authenticates a broker feed or completeness.
 */
export function auditDeclaredDemoQuoteIdentity(
  scope:DemoLifecycleScope,
  manifest:DemoStatementPopulationManifest,
  orders:readonly DemoStatementOrder[]
):DemoQuoteIdentityReview {
  const population=auditDeclaredDemoStatementPopulation(scope,manifest,orders);
  const byId=new Map<string,QuoteSnapshot>();
  const occurrences=new Map<string,number>();
  const conflicts:DemoQuoteIdentityReview['conflicts'][number][]=[];
  const conflictIds=new Set<string>();
  let fills=0;
  for(const order of orders){
    for(const event of order.events){
      if(event.kind!=='FILL')continue;
      fills++;
      const quote:QuoteSnapshot={
        eventId:event.eventId,observedAt:event.quoteObservedAt,
        bid:canonicalSix(event.quoteBid),ask:canonicalSix(event.quoteAsk),
        batchSha256:event.quoteBatchSha256
      };
      const prior=byId.get(event.quoteId);
      occurrences.set(event.quoteId,(occurrences.get(event.quoteId)??0)+1);
      if(!prior){byId.set(event.quoteId,quote);continue;}
      if(prior.observedAt!==quote.observedAt||prior.bid!==quote.bid||
         prior.ask!==quote.ask||prior.batchSha256!==quote.batchSha256){
        if(!conflictIds.has(event.quoteId)){
          conflicts.push({quoteId:event.quoteId,firstEventId:prior.eventId,
            conflictingEventId:event.eventId});
          conflictIds.add(event.quoteId);
        }
      }
    }
  }
  const status=conflicts.length>0?'CONFLICTING_DECLARED_QUOTE_ID' as const:
    population.status==='DECLARED_POPULATION_MISMATCH'?'DECLARED_POPULATION_MISMATCH' as const:
    fills===0?'NO_DECLARED_FILLS' as const:
      'CONSISTENT_DECLARED_QUOTE_IDS_UNVERIFIED' as const;
  return {coverage:'SELF_DECLARED_DEMO_QUOTE_IDS_ONLY',status,
    statementPopulation:population.status,fillEvents:fills,
    distinctQuoteIds:byId.size,
    reusedQuoteIds:[...occurrences.values()].filter(n=>n>1).length,
    conflictingQuoteIds:[...conflictIds].sort(),
    conflicts:conflicts.sort((a,b)=>a.quoteId.localeCompare(b.quoteId)),
    mayExecuteOrder:false,warnings:[
      'All quotes, order events, source identities, hashes and statement manifests are caller-declared, not authenticated broker evidence.',
      'Matching quote IDs do not prove that snapshots were executable, complete, contemporaneous with market liquidity or free of spread manipulation.',
      'A conflicting quote ID or mismatched statement population must be reconciled before using declared fills for cost or risk research.',
      'No fills means no declared fill evidence, not zero real fills, zero costs or zero risk.',
      'No real/demo broker adapter, trading permission, margin, financing, currency conversion or profitability is established.'
    ]};
}
