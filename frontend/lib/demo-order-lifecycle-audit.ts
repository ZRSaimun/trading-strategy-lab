/** Offline, fail-closed reconciliation of self-declared demo broker order events.
 * Does not contact a broker, submit/cancel orders, authenticate exports or calculate P&L.
 */
export type DemoLifecycleScope = Readonly<{
  provider:string; venue:string; instrument:string; accountAlias:string;
  quoteCurrency:string; statementSha256:string; quoteBatchSha256:string;
  asOf:number; maxQuoteAgeMs:number;
}>;
export type DemoLifecycleIntent = Readonly<{
  clientOrderId:string; side:'BUY'|'SELL'; requestedContracts:number;
  submittedAt:number; expiresAt:number;
}>;
type Common = Readonly<{
  eventId:string; clientOrderId:string; provider:string; venue:string;
  instrument:string; accountAlias:string; statementSha256:string;
  at:number; recordedAt:number;
}>;
export type DemoLifecycleEvent =
  | (Common & Readonly<{kind:'ACK';brokerOrderId:string}>)
  | (Common & Readonly<{kind:'FILL';fillId:string;contracts:number;price:string;
      commissionCurrency:string;quoteId:string;quoteObservedAt:number;
      quoteBid:string;quoteAsk:string;quoteBatchSha256:string}>)
  | (Common & Readonly<{kind:'CANCEL_REQUESTED'|'CANCELED'|'EXPIRED'|'REJECTED'}>);
export type DemoLifecycleStatus = 'SUBMITTED'|'ACKNOWLEDGED'|'PARTIALLY_FILLED'|
  'CANCEL_PENDING'|'FILLED'|'CANCELED'|'EXPIRED'|'REJECTED';
export type DemoLifecycleReview = Readonly<{
  coverage:'SELF_DECLARED_OFFLINE_DEMO_EVENTS_ONLY';
  status:DemoLifecycleStatus; brokerOrderId:string|null;
  requestedContracts:number; filledContracts:number; remainingContracts:number;
  averageFillPrice:string|null; totalCommissionCurrency:string;
  eventCount:number; fillCount:number; terminal:boolean;
  warnings:readonly string[];
}>;
const SHA=/^[a-f0-9]{64}$/;
const ID=/^[A-Za-z0-9._:-]{1,120}$/;
const CUR=/^[A-Z]{3}$/;
const TIME=(v:unknown):v is number=>typeof v==='number'&&Number.isSafeInteger(v)&&v>=0;
const COUNT=(v:unknown):v is number=>typeof v==='number'&&Number.isSafeInteger(v)&&v>0&&v<=1_000_000;
const BASE=['eventId','clientOrderId','provider','venue','instrument','accountAlias',
  'statementSha256','at','recordedAt','kind'];
function exact(value:unknown,expected:readonly string[],label:string):void {
  if(!value||typeof value!=='object'||Array.isArray(value)||
    Object.keys(value).length!==expected.length||
    Object.keys(value).some(k=>!expected.includes(k))) throw Error('Invalid '+label+' schema');
}
function decimal(value:unknown,places:number,label:string):bigint {
  const regex=places===6?/^(?:0|[1-9][0-9]{0,7})(?:\.[0-9]{1,6})?$/:/^(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,2})?$/;
  if(typeof value!=='string'||!regex.test(value))throw Error('Invalid '+label+' decimal');
  const [whole,frac='']=value.split('.');
  return BigInt(whole)*10n**BigInt(places)+BigInt(frac.padEnd(places,'0')||'0');
}
function money(value:bigint,places:number):string {
  const unit=10n**BigInt(places);
  return String(value/unit)+'.'+String(value%unit).padStart(places,'0');
}
/** Explicit event population only: absent fills remain absent, not zero-cost fills.
 * Cancel requests are NOT broker cancellations; fills may occur until CANCELED.
 */
export function auditDeclaredDemoOrderLifecycle(
  scope:DemoLifecycleScope,intent:DemoLifecycleIntent,
  events:readonly DemoLifecycleEvent[]
):DemoLifecycleReview {
  exact(scope,['provider','venue','instrument','accountAlias','quoteCurrency',
    'statementSha256','quoteBatchSha256','asOf','maxQuoteAgeMs'],'demo scope');
  if(![scope.provider,scope.venue,scope.instrument,scope.accountAlias].every(v=>
    typeof v==='string'&&ID.test(v))||!CUR.test(scope.quoteCurrency)||
    !SHA.test(scope.statementSha256)||!SHA.test(scope.quoteBatchSha256)||
    !TIME(scope.asOf)||!TIME(scope.maxQuoteAgeMs)||
    scope.maxQuoteAgeMs===0||scope.maxQuoteAgeMs>300_000)
    throw Error('Invalid demo source identity or quote policy');
  exact(intent,['clientOrderId','side','requestedContracts','submittedAt','expiresAt'],'demo intent');
  if(!ID.test(intent.clientOrderId)||!['BUY','SELL'].includes(intent.side)||
    !COUNT(intent.requestedContracts)||!TIME(intent.submittedAt)||
    !TIME(intent.expiresAt)||intent.expiresAt<=intent.submittedAt||
    intent.submittedAt>scope.asOf)
    throw Error('Invalid demo intent or interval');
  if(!Array.isArray(events)||events.length>5000)throw Error('Unbounded demo event population');
  const eventIds=new Set<string>(),fillIds=new Set<string>();
  let status:DemoLifecycleStatus='SUBMITTED',brokerOrderId:string|null=null;
  let filled=0,commission=0n,weightedPrice=0n,fillCount=0;
  let lastAt=intent.submittedAt,lastRecorded=intent.submittedAt;
  for(const event of events){
    if(!event||typeof event!=='object')throw Error('Invalid demo event');
    const keys=event.kind==='ACK'?[...BASE,'brokerOrderId']:
      event.kind==='FILL'?[...BASE,'fillId','contracts','price','commissionCurrency',
        'quoteId','quoteObservedAt','quoteBid','quoteAsk','quoteBatchSha256']:BASE;
    exact(event,keys,'demo event');
    if(!ID.test(event.eventId)||eventIds.has(event.eventId)||
      event.clientOrderId!==intent.clientOrderId||event.provider!==scope.provider||
      event.venue!==scope.venue||event.instrument!==scope.instrument||
      event.accountAlias!==scope.accountAlias||
      event.statementSha256!==scope.statementSha256||
      !TIME(event.at)||!TIME(event.recordedAt)||event.at<lastAt||
      event.recordedAt<lastRecorded||event.recordedAt<event.at||
      event.recordedAt>scope.asOf)
      throw Error('Duplicate, out-of-order, future or cross-source demo event');
    if(['FILLED','CANCELED','EXPIRED','REJECTED'].includes(status))
      throw Error('Demo event after terminal order state');
    if(event.kind==='ACK'){
      if(status!=='SUBMITTED'||!ID.test(event.brokerOrderId)||event.at>intent.expiresAt)
        throw Error('Invalid or repeated demo broker acknowledgment');
      brokerOrderId=event.brokerOrderId;status='ACKNOWLEDGED';
    }else if(event.kind==='FILL'){
      if(!['ACKNOWLEDGED','PARTIALLY_FILLED','CANCEL_PENDING'].includes(status)||
        event.at>intent.expiresAt||!ID.test(event.fillId)||fillIds.has(event.fillId)||
        !ID.test(event.quoteId)||!COUNT(event.contracts)||
        filled+event.contracts>intent.requestedContracts||
        event.quoteBatchSha256!==scope.quoteBatchSha256||
        !TIME(event.quoteObservedAt)||event.quoteObservedAt<=intent.submittedAt||
        event.quoteObservedAt>event.at||
        event.at-event.quoteObservedAt>scope.maxQuoteAgeMs)
        throw Error('Invalid, stale, duplicate or excessive demo fill');
      const price=decimal(event.price,6,'fill price');
      const bid=decimal(event.quoteBid,6,'bid');
      const ask=decimal(event.quoteAsk,6,'ask');
      const fee=decimal(event.commissionCurrency,2,'commission');
      if(price===0n||bid===0n||ask===0n||ask<bid)
        throw Error('Invalid demo bid/ask or fill price');
      weightedPrice+=price*BigInt(event.contracts);
      commission+=fee;filled+=event.contracts;fillCount++;
      fillIds.add(event.fillId);
      status=filled===intent.requestedContracts?'FILLED':
        status==='CANCEL_PENDING'?'CANCEL_PENDING':'PARTIALLY_FILLED';
    }else if(event.kind==='CANCEL_REQUESTED'){
      if(!['ACKNOWLEDGED','PARTIALLY_FILLED'].includes(status))
        throw Error('Invalid or repeated demo cancel request');
      status='CANCEL_PENDING';
    }else if(event.kind==='CANCELED'){
      if(!['ACKNOWLEDGED','PARTIALLY_FILLED','CANCEL_PENDING'].includes(status))
        throw Error('Demo cancellation without accepted order');
      status='CANCELED';
    }else if(event.kind==='EXPIRED'){
      if(event.at<intent.expiresAt)throw Error('Demo expiry before intent deadline');
      status='EXPIRED';
    }else if(event.kind==='REJECTED'){
      if(status!=='SUBMITTED')throw Error('Demo rejection after acceptance');
      status='REJECTED';
    }else throw Error('Unsupported demo event kind');
    eventIds.add(event.eventId);lastAt=event.at;lastRecorded=event.recordedAt;
  }
  const terminal=['FILLED','CANCELED','EXPIRED','REJECTED'].includes(status);
  // Exact integer weighted mean, rounded half-up at the sixth decimal place.
  const average=filled===0?null:money((weightedPrice+BigInt(filled)/2n)/BigInt(filled),6);
  return {coverage:'SELF_DECLARED_OFFLINE_DEMO_EVENTS_ONLY',status,brokerOrderId,
    requestedContracts:intent.requestedContracts,filledContracts:filled,
    remainingContracts:intent.requestedContracts-filled,averageFillPrice:average,
    totalCommissionCurrency:money(commission,2),eventCount:events.length,fillCount,terminal,
    warnings:[
      'Events, quote snapshots, timestamps, and statement hashes are caller declarations, not authenticated broker records.',
      'A cancel request does not cancel an order; partial fills and remaining quantity persist until a terminal broker event.',
      'An absent fill or terminal event is unknown, not evidence of no fill or no financial exposure.',
      'This is an offline audit, not a demo/live broker adapter, execution permission, margin model, or profit estimate.'
    ]};
}
