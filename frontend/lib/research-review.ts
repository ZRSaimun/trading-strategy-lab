/** Saved-research robustness diagnostics; no strategy fitting or trade execution.
 * These reviews interpret existing deterministic backtest reports and do NOT
 * reconstruct missing broker fills, future returns or statistical significance.
 */
import type {Bar} from './research.ts';
import type {Config} from './backtest.ts';

export type SnapshotMetrics={
 trades:number; netReturn:number; maxDrawdownPercent:number;
 winRate:number|null; profitFactor:number|null;
};
export type ResearchSnapshot={strategy:string;ruleVersion?:string;engine?:string;config?:Config;start?:number;end?:number;bars?:number;metrics:SnapshotMetrics};
export type ResearchSegment={name:string;reports:ResearchSnapshot[]};
export type ResearchRun={
 id:string;title:string;created_at:number;
 payload:{reports:ResearchSnapshot[];splits:ResearchSegment[];candles?:Bar[];
  notes?:string;source?:string;datasetHash?:string;
  window?:{start:number;end:number;bars:number}};
};
export type ReviewFinding={code:string;severity:'caution'|'context';message:string};
export type StrategyReview={
 strategy:string;ruleVersion:string;full:SnapshotMetrics|null;
 development:SnapshotMetrics|null;validation:SnapshotMetrics|null;
 holdout:SnapshotMetrics|null;findings:ReviewFinding[];
};
export type RobustnessReview={
 id:string;title:string;source:string;datasetHash:string;
 window:{start:number;end:number;bars:number}|null;
 strategies:StrategyReview[];runFindings:ReviewFinding[];
};

function checkedMetrics(m:SnapshotMetrics):SnapshotMetrics{
 if(!m||!Number.isSafeInteger(m.trades)||m.trades<0||
    !Number.isFinite(m.netReturn)||!Number.isFinite(m.maxDrawdownPercent)||
    m.maxDrawdownPercent<0||
    (m.winRate!==null&&(!Number.isFinite(m.winRate)||m.winRate<0||m.winRate>100))||
    (m.profitFactor!==null&&(!Number.isFinite(m.profitFactor)||m.profitFactor<0)))
  throw Error('Saved metrics are malformed or non-finite; cannot review this run');
 return m;
}
function lookup(reports:ResearchSnapshot[],strategy:string):SnapshotMetrics|null{
 const matching=reports.filter(r=>r.strategy===strategy);
 if(matching.length>1)throw Error('Ambiguous duplicate strategy identity in saved backtest');
 return matching.length?checkedMetrics(matching[0].metrics):null;
}
const finding=(code:string,severity:ReviewFinding['severity'],message:string):ReviewFinding=>({code,severity,message});

/** Flag analysis, never a predictive score or profitability certification. */
export function reviewResearchRun(run:ResearchRun):RobustnessReview{
 if(!run||typeof run.id!=='string'||!run.payload||
    !Array.isArray(run.payload.reports)||!Array.isArray(run.payload.splits)||
    run.payload.splits.some(s=>!s||typeof s.name!=='string'||!Array.isArray(s.reports)))
  throw Error('Saved backtest lacks the required reports or chronological split records');
 const scopes=['Development 60%','Validation 20%','Holdout 20%'];
 const segments=scopes.map(name=>run.payload.splits.filter(s=>s.name===name));
 if(segments.some(arr=>arr.length>1))throw Error('Duplicate chronological split labels in saved backtest');
 const [development,validation,holdout]=segments.map(xs=>xs[0]?.reports||[]);
 const runFindings:ReviewFinding[]=[];
 if(segments.some(xs=>!xs.length))
  runFindings.push(finding('MISSING_SPLITS','caution','Missing a development, validation or holdout segment. Robustness across time cannot be assessed.'));
 if(/\bcapp?ed\b|\b2,000\b|\blimited window\b|\bnot a full archive\b/i.test(run.payload.notes||''))
  runFindings.push(finding('WINDOW_CAPPED','caution','The reported input window is capped or incomplete; conclusions do not cover the whole historical archive.'));
 if(!run.payload.source||/unknown/i.test(run.payload.source)||!run.payload.datasetHash||/unknown/i.test(run.payload.datasetHash))
  runFindings.push(finding('UNKNOWN_PROVENANCE','caution','Source or dataset fingerprint is missing. Verify exact history provenance before trusting comparisons.'));
 runFindings.push(finding('NO_INDEPENDENT_HOLDOUT','context','These saved chronological splits may have been inspected repeatedly. They are not independently secured, untouched forward data.'));
 runFindings.push(finding('EXECUTION_LIMITS','context','OHLC-only trading and user-modelled costs are not broker fills, executable spreads or verified live profits.'));
 const ids=[...new Set(run.payload.reports.map(r=>r.strategy))];
 if(ids.some(x=>typeof x!=='string'||!x))throw Error('Saved report has an invalid strategy identity');
 if(!ids.length)runFindings.push(finding('NO_STRATEGIES','caution','This saved run has no strategy reports.'));
 const strategies=ids.map(strategy=>{
  const full=lookup(run.payload.reports,strategy);
  const dev=lookup(development,strategy),val=lookup(validation,strategy),test=lookup(holdout,strategy);
  const ruleVersion=run.payload.reports.find(r=>r.strategy===strategy)?.ruleVersion||'Unspecified';
  const findings:ReviewFinding[]=[];
  if(!dev||!val||!test)
   findings.push(finding('UNAVAILABLE_SPLIT','caution','This strategy is missing at least one chronological segment.'));
  if(!full?.trades)
   findings.push(finding('NO_TRADES','caution','No completed simulated trades; there is no observed win rate or evidence of an edge.'));
  if(test&&test.trades<30)
   findings.push(finding('SMALL_HOLDOUT','caution',`Only ${test.trades} holdout trades. Treat comparisons as descriptive, not statistically convincing.`));
  if(dev&&test&&dev.netReturn>0&&test.netReturn<0)
   findings.push(finding('RETURN_REVERSAL','caution','Positive development return became negative in the later holdout period.'));
  else if(test&&test.netReturn<0)
   findings.push(finding('NEGATIVE_HOLDOUT','caution','The holdout return is negative under the modelled costs.'));
  if(dev&&test&&dev.winRate!==null&&test.winRate!==null&&dev.winRate-test.winRate>=15)
   findings.push(finding('WIN_RATE_DROP','caution','Holdout win rate is at least 15 percentage points below development (a descriptive threshold, not a significance test).'));
  if([full,dev,val,test].some(m=>m&&m.maxDrawdownPercent>=20))
   findings.push(finding('LARGE_DRAWDOWN','caution','At least one report shows 20% or greater close-marked drawdown; intrabar risk may be worse.'));
  if(test&&test.trades>0&&test.profitFactor===null)
   findings.push(finding('UNDEFINED_PROFIT_FACTOR','context','Holdout profit factor is undefined, not infinite proof of a winning system.'));
  return {strategy,ruleVersion,full,development:dev,validation:val,holdout:test,findings};
 });
 return {id:run.id,title:run.title,source:run.payload.source||'Unknown',
  datasetHash:run.payload.datasetHash||'Unknown',window:run.payload.window||null,
  strategies,runFindings};
}
