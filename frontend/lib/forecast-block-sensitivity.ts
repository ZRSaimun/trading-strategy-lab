/**
 * Block-deletion sensitivity of descriptive forward Brier deterioration.
 * This is OFFLINE research, not a significance test, feed authentication,
 * live alert permission, or evidence of profitable trading.
 */
import {reviewForwardCalibration} from './forecast-review-outbox.ts';
import type {FeedIdentity,ForecastRecord} from './forward-forecast-ledger.ts';

export type ForecastBlockSensitivity={
  mode:'UNVERIFIED_LOCAL_RESEARCH';live:false;
  status:'INSUFFICIENT'|'REPORT';reason:string|null;
  modelVersion:string;horizon:1|3|12;window:number;blockSize:number;
  comparisons:number;originalDeltaBrier:number|null;
  minDeltaBrier:number|null;maxDeltaBrier:number|null;
  fractionDeltaAtLeast002:number|null;fractionRecentAboveFixedBaseline:number|null;
  allDeltaAtLeast002:boolean|null;allRecentAboveFixedBaseline:boolean|null;
  latestTargetClose:number|null;
};
const loss=(r:ForecastRecord)=>(r.probability-Number(r.outcomeUp))**2;

/**
 * First apply the existing exact-source, causal, fixed-UTC-phase review gate.
 * For each earlier/recent window, independently delete one contiguous block
 * of equal length. Examine all block-pair omissions (k*k comparisons).
 * This deliberately reports sensitivity, NOT a p-value, bootstrap CI or
 * independent observations; the data may be serially dependent.
 */
export function evaluateForecastBlockSensitivity(
  records:readonly ForecastRecord[],identity:FeedIdentity,modelVersion:string,
  horizon:1|3|12,asOf:number,window=20,blockSize=5,
):ForecastBlockSensitivity{
  if(!Number.isSafeInteger(blockSize)||blockSize<2||
     !Number.isSafeInteger(window)||window%blockSize!==0||
     window/blockSize<3)
    throw Error('Block size must divide the window into at least three contiguous blocks');
  const review=reviewForwardCalibration(records,identity,modelVersion,horizon,asOf,window);
  const base={mode:'UNVERIFIED_LOCAL_RESEARCH' as const,live:false as const,
    modelVersion,horizon,window,blockSize};
  if(review.status==='INSUFFICIENT')
    return {...base,status:'INSUFFICIENT',reason:review.reasons.join(' '),
      comparisons:0,originalDeltaBrier:null,minDeltaBrier:null,maxDeltaBrier:null,
      fractionDeltaAtLeast002:null,fractionRecentAboveFixedBaseline:null,
      allDeltaAtLeast002:null,allRecentAboveFixedBaseline:null,latestTargetClose:null};
  // The review gate already validated every matching record and selected
  // exactly two complete, contiguous, settled non-overlapping windows.
  const aligned=records.filter(r=>r.modelVersion===modelVersion&&r.horizon===horizon&&
    (r.baseStart/identity.seconds)%horizon===0).sort((a,b)=>a.baseStart-b.baseStart);
  const selected=aligned.slice(-2*window);
  if(selected.length!==2*window||selected.some(r=>r.status!=='SETTLED')||
     review.deltaBrier===null||review.latestTargetClose===null)
    throw Error('Inconsistent validated calibration window');
  const earlier=selected.slice(0,window).map(loss);
  const recent=selected.slice(window).map(loss);
  const blocks=window/blockSize,retained=window-blockSize;
  const sum=(xs:readonly number[])=>xs.reduce((a,b)=>a+b,0);
  const earlierTotal=sum(earlier),recentTotal=sum(recent);
  const earlierOmissions=Array.from({length:blocks},(_,i)=>
    sum(earlier.slice(i*blockSize,(i+1)*blockSize)));
  const recentOmissions=Array.from({length:blocks},(_,i)=>
    sum(recent.slice(i*blockSize,(i+1)*blockSize)));
  let minDelta=Infinity,maxDelta=-Infinity,deteriorated=0,aboveBaseline=0;
  for(let i=0;i<blocks;i++){
    const earlierMean=(earlierTotal-earlierOmissions[i])/retained;
    for(let j=0;j<blocks;j++){
      const recentMean=(recentTotal-recentOmissions[j])/retained;
      const delta=recentMean-earlierMean;
      minDelta=Math.min(minDelta,delta);maxDelta=Math.max(maxDelta,delta);
      if(delta>=0.02) deteriorated++;
      if(recentMean>0.25) aboveBaseline++;
    }
  }
  const comparisons=blocks*blocks;
  return {...base,status:'REPORT',reason:null,comparisons,
    originalDeltaBrier:review.deltaBrier,minDeltaBrier:minDelta,maxDeltaBrier:maxDelta,
    fractionDeltaAtLeast002:deteriorated/comparisons,
    fractionRecentAboveFixedBaseline:aboveBaseline/comparisons,
    allDeltaAtLeast002:deteriorated===comparisons,
    allRecentAboveFixedBaseline:aboveBaseline===comparisons,
    latestTargetClose:review.latestTargetClose};
}
