/**
 * Disconnected causal directional-frequency baseline for completed candles.
 * It never authenticates the caller's receipt timestamps, calibrates itself,
 * generates trade signals, or connects to a quote/broker/notification service.
 */
import type {CompletedCandle,FeedIdentity} from './forward-forecast-ledger.ts';

export type ReceivedCompletedCandle=CompletedCandle & {receivedAt:number};
export type BaselineHorizon=1|3|12;
export type HorizonBaseline={
 horizon:BaselineHorizon;status:'READY_OFFLINE_ONLY'|'INSUFFICIENT';
 samples:number;up:number;probabilityUp:number|null;
 earliestOutcomeClose:number|null;latestOutcomeClose:number|null;
};
export type CausalFrequencyBaseline={
 mode:'UNVERIFIED_LOCAL_RESEARCH';live:false;execution:'NONE';quoteTimestamp:null;
 modelVersion:'jeffreys-frequency-v1';identity:FeedIdentity;
 baseStart:number;issuedAsOf:number;horizons:HorizonBaseline[];
};
const epoch=(n:number)=>Number.isSafeInteger(n)&&n>=0;
const sourceKey=(x:FeedIdentity)=>JSON.stringify([x.instrument,x.provider,x.venue,x.sourceId,x.priceSide,x.seconds]);
const HORIZONS:readonly BaselineHorizon[]=[1,3,12];
/**
 * Each h-step outcome uses a distinct backward, non-overlapping h-candle
 * interval ending at or before the latest observed close. Jeffreys Beta(1/2,1/2)
 * smoothing supplies an unconditional *uncalibrated* probability baseline.
 * No observations from after issuedAsOf may influence any estimate.
 */
export function estimateCausalFrequencyBaseline(
 candles:readonly ReceivedCompletedCandle[],issuedAsOf:number,
 config:{minSamples?:number;maxSamples?:number;maxLagSeconds?:number}={},
):CausalFrequencyBaseline{
 const min=config.minSamples??20,max=config.maxSamples??60,lag=config.maxLagSeconds??120;
 if(!epoch(issuedAsOf)||!Number.isSafeInteger(min)||min<10||min>500||
    !Number.isSafeInteger(max)||max<min||max>2000||
    !Number.isSafeInteger(lag)||lag<0||lag>3600||
    !Array.isArray(candles)||candles.length<1||candles.length>100000)
  throw Error('Invalid offline baseline configuration');
 const identity=candles[0].identity;
 if(!identity||!identity.instrument?.trim()||!identity.provider?.trim()||
    !identity.venue?.trim()||!identity.sourceId?.trim()||
    !['bid','ask','mid'].includes(identity.priceSide)||
    !Number.isSafeInteger(identity.seconds)||identity.seconds<60||identity.seconds%60!==0)
  throw Error('Invalid source identity');
 const expected=sourceKey(identity),step=identity.seconds;
 let previousStart=-1,previousReceipt=-1;
 for(const candle of candles){
  const closeAt=candle.start+step;
  if(sourceKey(candle.identity)!==expected||!epoch(candle.start)||
     candle.start%step!==0||!epoch(closeAt)||
     !Number.isFinite(candle.close)||candle.close<=0||
     !epoch(candle.receivedAt)||candle.receivedAt<closeAt||
     candle.receivedAt-closeAt>lag||candle.receivedAt>issuedAsOf||
     (previousStart>=0&&candle.start!==previousStart+step)||
     candle.receivedAt<previousReceipt)
   throw Error('Untrusted, missing, revised, mixed, stale or future completed-candle observation');
  previousStart=candle.start;previousReceipt=candle.receivedAt;
 }
 const last=candles[candles.length-1],lastClose=last.start+step;
 if(issuedAsOf<last.receivedAt||issuedAsOf-lastClose>lag||
    !epoch(lastClose+step)||issuedAsOf>=lastClose+step)
  throw Error('No causally fresh base candle before the next completed close');
 const horizons=HORIZONS.map((horizon):HorizonBaseline=>{
  let up=0,samples=0,earliestOutcomeClose:number|null=null;
  for(let end=candles.length-1;end>=horizon&&samples<max;end-=horizon){
   if(candles[end].close>candles[end-horizon].close)up++;
   samples++;
   earliestOutcomeClose=candles[end].start+step;
  }
  const ready=samples>=min;
  return {horizon,status:ready?'READY_OFFLINE_ONLY':'INSUFFICIENT',
   samples,up,probabilityUp:ready?(up+0.5)/(samples+1):null,
   earliestOutcomeClose,latestOutcomeClose:samples?lastClose:null};
 });
 return {mode:'UNVERIFIED_LOCAL_RESEARCH',live:false,execution:'NONE',
  quoteTimestamp:null,modelVersion:'jeffreys-frequency-v1',identity:{...identity},
  baseStart:last.start,issuedAsOf,horizons};
}
