/**
 * Prospective, in-memory forecast journal core. No historical replay, broker,
 * provider, network, persistence, or order execution is connected here.
 * The caller must provide a trusted receipt-time clock and authentic feed.
 */
export type FeedIdentity={instrument:string;provider:string;venue:string;sourceId:string;priceSide:'bid'|'ask'|'mid';seconds:number};
export type CompletedCandle={identity:FeedIdentity;start:number;close:number};
export type ForecastIssue={id:string;modelVersion:string;horizon:1|3|12;probability:number};
export type ForecastRecord={
 id:string;modelVersion:string;horizon:1|3|12;probability:number;
 instrument:string;provider:string;venue:string;sourceId:string;priceSide:FeedIdentity['priceSide'];seconds:number;
 baseStart:number;baseClose:number;issuedAt:number;targetStart:number;
 status:'PENDING'|'SETTLED'|'VOID_GAP';
 resolvedAt:number|null;outcomeUp:boolean|null;reason:string|null;
};
export type ForecastSummary={issued:number;pending:number;settled:number;voidGap:number;brier:number|null;logLoss:number|null;referenceBrier:number|null};

const finite=(n:number)=>Number.isFinite(n);
const validEpoch=(n:number)=>Number.isSafeInteger(n)&&n>=0;
const key=(f:FeedIdentity)=>JSON.stringify([f.instrument,f.provider,f.venue,f.sourceId,f.priceSide,f.seconds]);
const clone=(f:ForecastRecord):ForecastRecord=>({...f});
const summarize=(entries:readonly ForecastRecord[]):ForecastSummary=>{
 const settled=entries.filter(e=>e.status==='SETTLED');
 const brier=settled.length?settled.reduce((sum,e)=>sum+(e.probability-Number(e.outcomeUp))**2,0)/settled.length:null;
 const logLoss=settled.length?settled.reduce((sum,e)=>sum-(e.outcomeUp?Math.log(e.probability):Math.log1p(-e.probability)),0)/settled.length:null;
 return {issued:entries.length,pending:entries.filter(e=>e.status==='PENDING').length,settled:settled.length,
  voidGap:entries.filter(e=>e.status==='VOID_GAP').length,brier,logLoss,referenceBrier:settled.length?0.25:null};
};

export class ForwardForecastLedger{
 private last:{start:number;close:number;receivedAt:number}|null=null;
 private lastActionAt=-1;
 private readonly forecasts=new Map<string,ForecastRecord>();
 private readonly issuedKeys=new Set<string>();
 private readonly identityKey:string;
 readonly identity:Readonly<FeedIdentity>;
 private readonly clock:()=>number;
 readonly maxLagSeconds:number;
 constructor(identity:FeedIdentity,clock:()=>number=()=>Math.floor(Date.now()/1000),maxLagSeconds=120){
  if(!identity.instrument.trim()||!identity.provider.trim()||!identity.venue.trim()||!identity.sourceId.trim()||
     !['bid','ask','mid'].includes(identity.priceSide)||!Number.isSafeInteger(identity.seconds)||identity.seconds<60||
     identity.seconds%60!==0||!Number.isSafeInteger(maxLagSeconds)||maxLagSeconds<0||maxLagSeconds>3600)
   throw Error('Invalid exact feed identity, candle interval, or receipt lag');
  this.identity=Object.freeze({...identity});this.clock=clock;this.maxLagSeconds=maxLagSeconds;
  this.identityKey=key(this.identity);
 }
 private now(){
  const n=this.clock();
  if(!validEpoch(n)||n<this.lastActionAt)throw Error('Non-monotonic or invalid trusted receipt clock');
  return n;
 }
 /** Receive a genuinely new completed candle; never backfill past observations. */
 receive(candle:CompletedCandle):void{
  if(key(candle.identity)!==this.identityKey)throw Error('Feed identity mismatch');
  if(!validEpoch(candle.start)||candle.start%this.identity.seconds!==0||!finite(candle.close)||candle.close<=0)
   throw Error('Invalid aligned completed candle');
  const now=this.now();
  if(this.last&&candle.start===this.last.start&&candle.close===this.last.close)return; // exact replay is harmless
  if(this.last&&candle.start<=this.last.start)throw Error('Out-of-order or revised completed candle');
  const end=candle.start+this.identity.seconds;
  if(!Number.isSafeInteger(end)||now<end||now-end>this.maxLagSeconds)
   throw Error('Future or stale candle; forward forecasts require timely receipt');
  if(this.last){
   const gap=candle.start-this.last.start!==this.identity.seconds;
   for(const f of this.forecasts.values()){
    if(f.status!=='PENDING')continue;
    if(gap||f.targetStart<candle.start){f.status='VOID_GAP';f.resolvedAt=now;f.reason='Unobserved completed candle or missing target';}
    else if(f.targetStart===candle.start){f.status='SETTLED';f.resolvedAt=now;f.outcomeUp=candle.close>f.baseClose;}
   }
  }
  this.last={start:candle.start,close:candle.close,receivedAt:now};
  this.lastActionAt=now;
 }
 /** Issue once, after observing the base close and before the next candle. */
 issue(input:ForecastIssue):ForecastRecord{
  const now=this.now();
  if(!/^[A-Za-z0-9_-]{1,80}$/.test(input.id)||!input.modelVersion.trim()||input.modelVersion.length>80||
     ![1,3,12].includes(input.horizon)||!finite(input.probability)||input.probability<=0||input.probability>=1)
   throw Error('Invalid forecast identity, horizon or probability');
  const prior=this.forecasts.get(input.id);
  if(prior){
   if(prior.modelVersion!==input.modelVersion||prior.horizon!==input.horizon||prior.probability!==input.probability)
    throw Error('Conflicting forecast idempotency key');
   return clone(prior);
  }
  if(!this.last||now<this.last.receivedAt||now-(this.last.start+this.identity.seconds)>this.maxLagSeconds)
   throw Error('No recent completed candle; cannot issue a forward forecast');
  const unique=JSON.stringify([this.last.start,input.horizon,input.modelVersion]);
  if(this.issuedKeys.has(unique))throw Error('Forecast already issued for this model, bar and horizon');
  const targetStart=this.last.start+input.horizon*this.identity.seconds;
  if(!Number.isSafeInteger(targetStart))throw Error('Target candle exceeds supported timestamp range');
  // A longer horizon must not bypass the first subsequent completed-candle boundary.
  // Without this gate, a delayed h=3/12 forecast could be issued after later
  // market outcomes were already observable but before its own target closed.
  const firstNextClose=this.last.start+2*this.identity.seconds;
  if(!Number.isSafeInteger(firstNextClose)||now>=firstNextClose)
   throw Error('Cannot issue retroactive forecast after the first subsequent candle close');
  const record:ForecastRecord={id:input.id,modelVersion:input.modelVersion,horizon:input.horizon,
   probability:input.probability,instrument:this.identity.instrument,provider:this.identity.provider,
   venue:this.identity.venue,sourceId:this.identity.sourceId,priceSide:this.identity.priceSide,
   seconds:this.identity.seconds,baseStart:this.last.start,baseClose:this.last.close,issuedAt:now,
   targetStart,status:'PENDING',resolvedAt:null,outcomeUp:null,reason:null};
  this.forecasts.set(input.id,record);this.issuedKeys.add(unique);this.lastActionAt=now;
  return clone(record);
 }
 entries():ForecastRecord[]{return [...this.forecasts.values()].map(clone)}
 /** Aggregate across horizons for backward compatibility; never infer per-horizon skill from this. */
 summary():ForecastSummary{return summarize(this.entries());}
 /** Disjoint per-horizon scoring prevents easy horizons from masking weak ones. */
 summaryByHorizon():Record<1|3|12,ForecastSummary>{
  const entries=this.entries();
  return {1:summarize(entries.filter(e=>e.horizon===1)),
          3:summarize(entries.filter(e=>e.horizon===3)),
          12:summarize(entries.filter(e=>e.horizon===12))};
 }
}
