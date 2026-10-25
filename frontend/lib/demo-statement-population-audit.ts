/** Cross-order, offline consistency audit of a *self-declared* demo statement manifest.
 * It cannot authenticate the manifest, prove it is complete, or grant execution.
 */
import {auditDeclaredDemoOrderLifecycle} from './demo-order-lifecycle-audit.ts';
import type {DemoLifecycleEvent, DemoLifecycleIntent, DemoLifecycleScope,
  DemoLifecycleStatus} from './demo-order-lifecycle-audit.ts';

export type DemoStatementPopulationManifest = Readonly<{
  provider:string; venue:string; instrument:string; accountAlias:string;
  statementSha256:string;
  expectedClientOrderIds:readonly string[];
  expectedEventIds:readonly string[];
  expectedFillIds:readonly string[];
  expectedBrokerOrderIds:readonly string[];
}>;
export type DemoStatementOrder = Readonly<{
  intent:DemoLifecycleIntent; events:readonly DemoLifecycleEvent[];
}>;
export type DemoPopulationDifference = Readonly<{
  missingDeclaredIds:readonly string[];
  unexpectedObservedIds:readonly string[];
}>;
export type DemoStatementPopulationReview = Readonly<{
  coverage:'SELF_DECLARED_STATEMENT_MANIFEST_ONLY';
  status:'DECLARED_POPULATION_MATCH_UNVERIFIED'|'DECLARED_POPULATION_MISMATCH';
  observedOrders:number; observedEvents:number; observedFills:number;
  observedAcknowledgments:number; observedTerminalOrders:number;
  differences:Readonly<{
    clientOrderIds:DemoPopulationDifference;
    eventIds:DemoPopulationDifference;
    fillIds:DemoPopulationDifference;
    brokerOrderIds:DemoPopulationDifference;
  }>;
  orderReviews:readonly Readonly<{
    clientOrderId:string; status:DemoLifecycleStatus;
    filledContracts:number; remainingContracts:number; terminal:boolean;
  }>[];
  warnings:readonly string[];
  mayExecuteOrder:false;
}>;
const ID=/^[A-Za-z0-9._:-]{1,120}$/;
const SHA=/^[a-f0-9]{64}$/;
const MAX_ORDERS=500,MAX_EVENTS=5000;
function exact(value:unknown,fields:readonly string[],label:string):void {
  if(!value||typeof value!=='object'||Array.isArray(value)||
    Object.keys(value).length!==fields.length||
    Object.keys(value).some(key=>!fields.includes(key)))
    throw Error('Invalid '+label+' schema');
}
function uniqueIds(value:unknown,max:number,label:string):Set<string> {
  if(!Array.isArray(value)||value.length>max)throw Error('Invalid '+label+' population');
  const ids=new Set<string>();
  for(const id of value){
    if(typeof id!=='string'||!ID.test(id)||ids.has(id))
      throw Error('Invalid or duplicate '+label+' identifier');
    ids.add(id);
  }
  return ids;
}
function difference(expected:Set<string>,observed:Set<string>):DemoPopulationDifference {
  return {
    missingDeclaredIds:[...expected].filter(id=>!observed.has(id)).sort(),
    unexpectedObservedIds:[...observed].filter(id=>!expected.has(id)).sort()
  };
}
/** A matching declaration is NOT evidence of a complete broker statement. */
export function auditDeclaredDemoStatementPopulation(
  scope:DemoLifecycleScope,manifest:DemoStatementPopulationManifest,
  orders:readonly DemoStatementOrder[]
):DemoStatementPopulationReview {
  exact(manifest,['provider','venue','instrument','accountAlias','statementSha256',
    'expectedClientOrderIds','expectedEventIds','expectedFillIds','expectedBrokerOrderIds'],
    'statement manifest');
  if(manifest.provider!==scope.provider||manifest.venue!==scope.venue||
    manifest.instrument!==scope.instrument||manifest.accountAlias!==scope.accountAlias||
    manifest.statementSha256!==scope.statementSha256||!SHA.test(manifest.statementSha256))
    throw Error('Cross-source demo statement manifest');
  const expected={
    clientOrderIds:uniqueIds(manifest.expectedClientOrderIds,MAX_ORDERS,'order'),
    eventIds:uniqueIds(manifest.expectedEventIds,MAX_EVENTS,'event'),
    fillIds:uniqueIds(manifest.expectedFillIds,MAX_EVENTS,'fill'),
    brokerOrderIds:uniqueIds(manifest.expectedBrokerOrderIds,MAX_ORDERS,'broker order')
  };
  if(!Array.isArray(orders)||orders.length===0||orders.length>MAX_ORDERS)
    throw Error('Invalid demo order population');
  const observed={clientOrderIds:new Set<string>(),eventIds:new Set<string>(),
    fillIds:new Set<string>(),brokerOrderIds:new Set<string>()};
  const orderReviews:DemoStatementPopulationReview['orderReviews'][number][]=[];
  let eventCount=0,fillCount=0,terminalCount=0;
  for(const order of orders){
    exact(order,['intent','events'],'statement order');
    if(!order.intent||typeof order.intent.clientOrderId!=='string'||
      observed.clientOrderIds.has(order.intent.clientOrderId))
      throw Error('Duplicate or invalid cross-order client ID');
    // Always validate the full individual lifecycle before counting any evidence.
    const review=auditDeclaredDemoOrderLifecycle(scope,order.intent,order.events);
    observed.clientOrderIds.add(order.intent.clientOrderId);
    if(review.brokerOrderId){
      if(observed.brokerOrderIds.has(review.brokerOrderId))
        throw Error('Duplicate cross-order broker order ID');
      observed.brokerOrderIds.add(review.brokerOrderId);
    }
    eventCount+=order.events.length;
    if(eventCount>MAX_EVENTS)throw Error('Unbounded cross-order event population');
    for(const event of order.events){
      if(observed.eventIds.has(event.eventId))throw Error('Duplicate cross-order event ID');
      observed.eventIds.add(event.eventId);
      if(event.kind==='FILL'){
        if(observed.fillIds.has(event.fillId))throw Error('Duplicate cross-order fill ID');
        observed.fillIds.add(event.fillId);fillCount++;
      }
    }
    if(review.terminal)terminalCount++;
    orderReviews.push({clientOrderId:order.intent.clientOrderId,status:review.status,
      filledContracts:review.filledContracts,remainingContracts:review.remainingContracts,
      terminal:review.terminal});
  }
  const differences={
    clientOrderIds:difference(expected.clientOrderIds,observed.clientOrderIds),
    eventIds:difference(expected.eventIds,observed.eventIds),
    fillIds:difference(expected.fillIds,observed.fillIds),
    brokerOrderIds:difference(expected.brokerOrderIds,observed.brokerOrderIds)
  };
  const mismatch=Object.values(differences).some(diff=>
    diff.missingDeclaredIds.length>0||diff.unexpectedObservedIds.length>0);
  return {coverage:'SELF_DECLARED_STATEMENT_MANIFEST_ONLY',
    status:mismatch?'DECLARED_POPULATION_MISMATCH':'DECLARED_POPULATION_MATCH_UNVERIFIED',
    observedOrders:orders.length,observedEvents:eventCount,observedFills:fillCount,
    observedAcknowledgments:observed.brokerOrderIds.size,observedTerminalOrders:terminalCount,
    differences,orderReviews,warnings:[
      'The expected-ID manifest and observed records are caller declarations, not authenticated broker exports.',
      'Matching sets cannot prove all real orders or fills were included; missing records remain unknown.',
      'Partially filled or cancel-pending orders retain potential exposure; no cash P&L is inferred.',
      'No order routing, live/demo execution permission, or profitability claim is provided.'
    ],mayExecuteOrder:false};
}