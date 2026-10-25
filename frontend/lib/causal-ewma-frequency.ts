/**
 * Causal, disconnected recency-weighted directional-frequency research model.
 * Validates all completed observations with the existing strict frequency
 * baseline before estimating any probability. No authenticated feed, orders,
 * notifications, persistence or forward performance are implied.
 */
import {
  estimateCausalFrequencyBaseline,
  type ReceivedCompletedCandle,
  type HorizonBaseline,
} from './causal-frequency-baseline.ts';
import type {FeedIdentity} from './forward-forecast-ledger.ts';

export type EwmaHorizon = {
  horizon:1|3|12;
  status:'READY_OFFLINE_ONLY'|'INSUFFICIENT';
  samples:number;
  up:number;
  effectiveSamples:number;
  weightedUpRate:number|null;
  probabilityUp:number|null;
  latestOutcomeClose:number|null;
};
export type EwmaForecast = {
  mode:'UNVERIFIED_LOCAL_RESEARCH';
  live:false;
  persisted:false;
  execution:'NONE';
  quoteTimestamp:null;
  modelVersion:'ewma-frequency-v1';
  identity:FeedIdentity;
  issuedAsOf:number;
  baseStart:number;
  halfLifeSamples:number;
  minEffectiveSamples:number;
  horizons:EwmaHorizon[];
};
const validInt=(n:number,min:number,max:number)=>
  Number.isSafeInteger(n)&&n>=min&&n<=max;

/**
 * Uses non-overlapping h-candle outcomes, counted backwards from the latest
 * completed candle, with exponentially decreasing weights by observation age.
 * Effective sample size (sum w)^2 / sum(w^2) determines abstention. The
 * smoothed probability is (weighted rate * ESS + 0.5)/(ESS + 1).
 *
 * This is a descriptive, uncalibrated baseline, NOT a Bayesian posterior,
 * independently verified forecast, or trading signal.
 */
export function estimateCausalEwmaFrequency(
  candles:readonly ReceivedCompletedCandle[],
  issuedAsOf:number,
  config:{
    halfLifeSamples?:number;
    minSamples?:number;
    minEffectiveSamples?:number;
    maxSamples?:number;
    maxLagSeconds?:number;
  }={},
):EwmaForecast{
  const halfLife=config.halfLifeSamples??20;
  const minSamples=config.minSamples??20;
  const maxSamples=config.maxSamples??120;
  const minEffective=config.minEffectiveSamples??10;
  if(!validInt(halfLife,2,500)||
     !validInt(minSamples,20,500)||
     !validInt(maxSamples,minSamples,2000)||
     !validInt(minEffective,10,maxSamples))
    throw Error('Invalid offline EWMA research configuration');

  // Reuse the full source, timestamp, receipt, gap and lookahead checks.
  // A subset of otherwise valid candles must never bypass these checks.
  const verified=estimateCausalFrequencyBaseline(candles,issuedAsOf,{
    minSamples,maxSamples,maxLagSeconds:config.maxLagSeconds,
  });
  const horizons=verified.horizons.map((h:HorizonBaseline):EwmaHorizon=>{
    let sumW=0,sumW2=0,sumUp=0;
    for(let i=0;i<h.samples;i++){
      const end=candles.length-1-i*h.horizon;
      const up=Number(candles[end].close>candles[end-h.horizon].close);
      const weight=Math.pow(0.5,i/halfLife);
      sumW+=weight;
      sumW2+=weight*weight;
      sumUp+=weight*up;
    }
    const effectiveSamples=sumW2>0?sumW*sumW/sumW2:0;
    const weightedUpRate=sumW>0?sumUp/sumW:null;
    const ready=h.samples>=minSamples&&effectiveSamples>=minEffective;
    const probabilityUp=ready&&weightedUpRate!==null?
      (weightedUpRate*effectiveSamples+0.5)/(effectiveSamples+1):null;
    return {
      horizon:h.horizon,
      status:ready?'READY_OFFLINE_ONLY':'INSUFFICIENT',
      samples:h.samples,
      up:h.up,
      effectiveSamples,
      weightedUpRate,
      probabilityUp,
      latestOutcomeClose:h.latestOutcomeClose,
    };
  });
  return {
    mode:'UNVERIFIED_LOCAL_RESEARCH',
    live:false,
    persisted:false,
    execution:'NONE',
    quoteTimestamp:null,
    modelVersion:'ewma-frequency-v1',
    identity:{...verified.identity},
    issuedAsOf,
    baseStart:verified.baseStart,
    halfLifeSamples:halfLife,
    minEffectiveSamples:minEffective,
    horizons,
  };
}
