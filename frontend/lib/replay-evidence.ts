import {validStructureSegments,type QualityBar} from './structure-quality.ts';

/** Read-only diagnostics of the revealed prefix, never the loaded future. */
export function replayEvidence(bars:readonly QualityBar[],frame:string){
 const segments=validStructureSegments(bars,frame);
 let unusableBars=0,discontinuities=0,observedMinutes=0;
 for(let i=0;i<bars.length;i++){
  if(segments[i]<0)unusableBars++;
  else if(i>0&&segments[i]===i)discontinuities++;
  const minutes=bars[i].observed_minutes;
  if(Number.isSafeInteger(minutes)&&minutes>0)observedMinutes+=minutes;
 }
 return {revealedBars:bars.length,firstBarOpen:bars[0]?.time??null,
  lastBarOpen:bars.at(-1)?.time??null,observedMinutes,unusableBars,discontinuities,
  state:!bars.length?'NO_DATA':unusableBars||discontinuities?'INSUFFICIENT_DATA':'OBSERVED_PREFIX'} as const;
}
