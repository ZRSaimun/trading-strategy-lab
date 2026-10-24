/**
 * Bounded, replay-validated checkpoint for the prospective forecast ledger.
 * This is a local state-recovery building block, NOT an authenticated feed,
 * tamper-proof audit log, durable server storage, or proof of forward testing.
 */
import {
 ForwardForecastLedger,
 type CompletedCandle,type FeedIdentity,type ForecastIssue,type ForecastRecord,type ForecastSummary,type ModelHorizonSummary,
} from './forward-forecast-ledger.ts';

export type ForecastJournalEvent =
 | {sequence:number;receivedAt:number;kind:'CANDLE';candle:CompletedCandle}
 | {sequence:number;receivedAt:number;kind:'FORECAST';forecast:ForecastIssue};
export type ForecastCheckpoint={
 version:1;evidence:'UNVERIFIED_LOCAL_EVENT_LOG';identity:FeedIdentity;
 maxLagSeconds:number;events:ForecastJournalEvent[];
};
const MAX_EVENTS=50000;
const validEpoch=(n:number)=>Number.isSafeInteger(n)&&n>=0;
const object=(v:unknown):v is Record<string,unknown>=>v!==null&&typeof v==='object'&&!Array.isArray(v);
const exactKeys=(value:Record<string,unknown>,keys:string[])=>
 Object.keys(value).length===keys.length&&keys.every(k=>Object.hasOwn(value,k));
const cloneEvent=(e:ForecastJournalEvent):ForecastJournalEvent=>
 e.kind==='CANDLE'?{sequence:e.sequence,receivedAt:e.receivedAt,kind:'CANDLE',
  candle:{identity:{...e.candle.identity},start:e.candle.start,close:e.candle.close}}:
 {sequence:e.sequence,receivedAt:e.receivedAt,kind:'FORECAST',forecast:{...e.forecast}};

export class ForwardForecastJournal{
 private actionTime=0;
 private readonly ledger:ForwardForecastLedger;
 private readonly events:ForecastJournalEvent[]=[];
 private readonly forecastIds=new Set<string>();
 private lastCandle:{start:number;close:number}|null=null;
 private readonly trustedClock:()=>number;
 readonly identity:Readonly<FeedIdentity>;
 readonly maxLagSeconds:number;
 constructor(identity:FeedIdentity,trustedClock:()=>number,maxLagSeconds=120){
  if([identity.instrument,identity.provider,identity.venue,identity.sourceId].some(s=>typeof s!=='string'||s.length>160))
   throw Error('Feed identity field exceeds bounded journal limit');
  this.ledger=new ForwardForecastLedger(identity,()=>this.actionTime,maxLagSeconds);
  this.identity=this.ledger.identity;
  this.maxLagSeconds=maxLagSeconds;
  this.trustedClock=trustedClock;
 }
 private atNow():number{
  const at=this.trustedClock();
  if(!validEpoch(at)||at<this.actionTime)throw Error('Invalid or backward trusted journal clock');
  return at;
 }
 private apply(event:ForecastJournalEvent):ForecastRecord|null{
  if(this.events.length>=MAX_EVENTS)throw Error('Journal event limit reached; persist and rotate with a reviewed storage design');
  if(event.sequence!==this.events.length+1||!validEpoch(event.receivedAt)||event.receivedAt<this.actionTime)
   throw Error('Malformed, reordered or backward journal event');
  const previous=this.actionTime;
  this.actionTime=event.receivedAt;
  let issued:ForecastRecord|null=null;
  try{
   if(event.kind==='CANDLE'){
    const duplicate=this.lastCandle?.start===event.candle.start&&this.lastCandle.close===event.candle.close;
    this.ledger.receive(event.candle);
    if(duplicate){this.actionTime=previous;return null;}
    this.lastCandle={start:event.candle.start,close:event.candle.close};
   }else{
    const duplicate=this.forecastIds.has(event.forecast.id);
    issued=this.ledger.issue(event.forecast);
    if(duplicate){this.actionTime=previous;return issued;}
    this.forecastIds.add(event.forecast.id);
   }
  }catch(error){this.actionTime=previous;throw error;}
  this.events.push(cloneEvent(event));
  return issued;
 }
 receive(candle:CompletedCandle):void{
  const at=this.atNow();
  this.apply({sequence:this.events.length+1,receivedAt:at,kind:'CANDLE',candle});
 }
 issue(forecast:ForecastIssue):ForecastRecord{
  const at=this.atNow();
  const record=this.apply({sequence:this.events.length+1,receivedAt:at,kind:'FORECAST',forecast});
  if(!record)throw Error('Forecast issuance was not recorded');
  return record;
 }
 entries():ForecastRecord[]{return this.ledger.entries();}
 summary():ForecastSummary{return this.ledger.summary();}
 summaryByHorizon():Record<1|3|12,ForecastSummary>{return this.ledger.summaryByHorizon();}
 summaryByModelAndHorizon():ModelHorizonSummary[]{return this.ledger.summaryByModelAndHorizon();}
 checkpoint():ForecastCheckpoint{
  return {version:1,evidence:'UNVERIFIED_LOCAL_EVENT_LOG',identity:{...this.identity},
   maxLagSeconds:this.maxLagSeconds,events:this.events.map(cloneEvent)};
 }
 /** Strict replay checks causal consistency, not authenticity of supplied events. */
 static restore(raw:unknown,trustedClock:()=>number):ForwardForecastJournal{
  if(!object(raw)||!exactKeys(raw,['version','evidence','identity','maxLagSeconds','events'])||
     raw.version!==1||raw.evidence!=='UNVERIFIED_LOCAL_EVENT_LOG'||!object(raw.identity)||
     !exactKeys(raw.identity,['instrument','provider','venue','sourceId','priceSide','seconds'])||
     !Array.isArray(raw.events)||raw.events.length>MAX_EVENTS)
   throw Error('Invalid or unsupported forecast checkpoint');
  const now=trustedClock();
  if(!validEpoch(now))throw Error('Invalid trusted restore clock');
  const journal=new ForwardForecastJournal(raw.identity as FeedIdentity,trustedClock,raw.maxLagSeconds as number);
  for(let i=0;i<raw.events.length;i++){
   const item:unknown=raw.events[i];
   if(!object(item)||!validEpoch(item.receivedAt as number)||(item.receivedAt as number)>now||
      item.sequence!==i+1||!['CANDLE','FORECAST'].includes(item.kind as string))
    throw Error('Malformed, future-dated or reordered journal event');
   if(item.kind==='CANDLE'){
    if(!exactKeys(item,['sequence','receivedAt','kind','candle'])||!object(item.candle)||
       !exactKeys(item.candle,['identity','start','close'])||!object(item.candle.identity)||
       !exactKeys(item.candle.identity,['instrument','provider','venue','sourceId','priceSide','seconds']))
     throw Error('Malformed candle journal event');
   }else if(!exactKeys(item,['sequence','receivedAt','kind','forecast'])||!object(item.forecast)||
            !exactKeys(item.forecast,['id','modelVersion','horizon','probability']))
    throw Error('Malformed forecast journal event');
   const before=journal.events.length;
   journal.apply(item as ForecastJournalEvent);
   if(journal.events.length===before)throw Error('Redundant duplicate journal event');
  }
  return journal;
 }
}
