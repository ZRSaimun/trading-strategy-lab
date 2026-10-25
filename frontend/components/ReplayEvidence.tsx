import {replayEvidence} from '../lib/replay-evidence';
import type {Bar} from '../lib/research';

export default function ReplayEvidence({bars,frame,source,sha256}:{bars:readonly Bar[];frame:string;source?:string;sha256?:string}){
 const evidence=replayEvidence(bars,frame);
 const utc=(time:number|null)=>time===null?'—':Number.isFinite(time)&&Math.abs(time)<8.64e12?new Date(time*1000).toISOString():'Invalid timestamp';
 return <section aria-label="Replay evidence"><h3>Replay evidence · revealed window</h3>
  <p>{evidence.state} · Historical research only. No execution.</p>
  <dl><dt>Exact source label</dt><dd>{source||'Unavailable'}</dd>
   <dt>Imported dataset SHA-256</dt><dd style={{overflowWrap:'anywhere'}}>{sha256||'Unavailable'}</dd>
   <dt>Timeframe / revealed bars</dt><dd>{frame} / {evidence.revealedBars}</dd>
   <dt>First revealed bar opens (UTC)</dt><dd>{utc(evidence.firstBarOpen)}</dd>
   <dt>Last revealed bar opens (UTC)</dt><dd>{utc(evidence.lastBarOpen)}</dd>
   <dt>Reported observed minutes</dt><dd>{evidence.observedMinutes}</dd>
   <dt>Unusable structural bars / run breaks</dt><dd>{evidence.unusableBars} / {evidence.discontinuities}</dd></dl>
  <p>Only revealed bars are counted. Run breaks include unknown gaps and recovery after unusable bars; closures are not classified. Daily and longer coverage is not certified. Source labels and the full imported-dataset hash are provenance references, not authentication or a hash of this prefix. No broker CFD spread, slippage or financing is evaluated here.</p>
 </section>;
}
