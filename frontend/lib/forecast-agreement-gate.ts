/**
 * Read-only cross-model agreement diagnostic for two correlated, offline
 * directional baselines. Never authenticates observations or authorizes
 * alerts, fills, broker orders, or real-money trading.
 */
import type {CausalFrequencyBaseline, HorizonBaseline} from './causal-frequency-baseline.ts';
import type {EwmaForecast, EwmaHorizon} from './causal-ewma-frequency.ts';

export type AgreementStatus =
  'ABSTAIN_INSUFFICIENT'|'ABSTAIN_CONFLICT'|'ABSTAIN_UNCERTAIN'|
  'CONSENSUS_UP_RESEARCH_ONLY'|'CONSENSUS_DOWN_RESEARCH_ONLY';
export type AgreementHorizon = {
  horizon:1|3|12;
  status:AgreementStatus;
  direction:'UP'|'DOWN'|null;
  frequencyProbability:number|null;
  ewmaProbability:number|null;
  absoluteDisagreement:number|null;
  probabilityRange:[number,number]|null;
  frequencySamples:number;
  ewmaEffectiveSamples:number;
};
export type ForecastAgreement = {
  mode:'UNVERIFIED_LOCAL_RESEARCH';live:false;authenticated:false;
  persisted:false;alertsEnabled:false;execution:'NONE';ordersSubmitted:0;
  issuedAsOf:number;assessedAt:number;
  identity:CausalFrequencyBaseline['identity'];
  horizons:AgreementHorizon[];
};
const epoch=(n:number)=>Number.isSafeInteger(n)&&n>=0;
const validProbability=(n:number)=>Number.isFinite(n)&&n>=0&&n<=1;
const key=(x:CausalFrequencyBaseline['identity'])=>
  JSON.stringify([x.instrument,x.provider,x.venue,x.sourceId,x.priceSide,x.seconds]);
const expected=[1,3,12] as const;
function validateHorizon(f:HorizonBaseline,e:EwmaHorizon,h:1|3|12):void{
  if(!f||!e||f.horizon!==h||e.horizon!==h||
     !Number.isSafeInteger(f.samples)||f.samples<0||
     !Number.isSafeInteger(f.up)||f.up<0||f.up>f.samples||
     !Number.isSafeInteger(e.samples)||e.samples!==f.samples||
     !Number.isSafeInteger(e.up)||e.up!==f.up||
     !Number.isFinite(e.effectiveSamples)||e.effectiveSamples<0||
     e.effectiveSamples>e.samples+1e-8||
     f.latestOutcomeClose!==e.latestOutcomeClose||
     !['READY_OFFLINE_ONLY','INSUFFICIENT'].includes(f.status)||
     !['READY_OFFLINE_ONLY','INSUFFICIENT'].includes(e.status))
    throw Error('Incompatible forecast horizon evidence');
  if((f.status==='READY_OFFLINE_ONLY')!== (f.probabilityUp!==null)||
     (e.status==='READY_OFFLINE_ONLY')!== (e.probabilityUp!==null)||
     (f.probabilityUp!==null&&!validProbability(f.probabilityUp))||
     (e.probabilityUp!==null&&!validProbability(e.probabilityUp))||
     (e.weightedUpRate!==null&&!validProbability(e.weightedUpRate))||
     (e.samples>0)!==(e.weightedUpRate!==null))
    throw Error('Malformed probability or abstention state');
}
/**
 * Both inputs must have been issued from the same candle, receipt clock and
 * exact feed identity. AssessedAt is caller-supplied, not an authenticated
 * server clock. Agreement is descriptive and NOT statistical independence,
 * calibrated confidence, a signal or a performance guarantee.
 */
export function assessOfflineForecastAgreement(
  frequency:CausalFrequencyBaseline,
  ewma:EwmaForecast,
  assessedAt:number,
  config:{maxAssessmentLagSeconds?:number;maxDisagreement?:number;minDirectionalMargin?:number}={},
):ForecastAgreement{
  const maxLag=config.maxAssessmentLagSeconds??60;
  const maxDiff=config.maxDisagreement??0.15;
  const margin=config.minDirectionalMargin??0.05;
  if(!Number.isSafeInteger(maxLag)||maxLag<0||maxLag>3600||
     !Number.isFinite(maxDiff)||maxDiff<=0||maxDiff>0.5||
     !Number.isFinite(margin)||margin<0||margin>=0.5)
    throw Error('Invalid research agreement configuration');
  if(!frequency||!ewma||frequency.mode!=='UNVERIFIED_LOCAL_RESEARCH'||
     ewma.mode!=='UNVERIFIED_LOCAL_RESEARCH'||frequency.live!==false||
     ewma.live!==false||ewma.persisted!==false||
     frequency.execution!=='NONE'||ewma.execution!=='NONE'||
     frequency.quoteTimestamp!==null||ewma.quoteTimestamp!==null||
     frequency.modelVersion!=='jeffreys-frequency-v1'||
     ewma.modelVersion!=='ewma-frequency-v1'||
     !frequency.identity||!ewma.identity||
     key(frequency.identity)!==key(ewma.identity)||
     !Number.isSafeInteger(frequency.identity.seconds)||frequency.identity.seconds<60||
     !epoch(frequency.baseStart)||!epoch(ewma.baseStart)||
     frequency.baseStart!==ewma.baseStart||
     !epoch(frequency.issuedAsOf)||frequency.issuedAsOf!==ewma.issuedAsOf||
     !epoch(assessedAt)||assessedAt<frequency.issuedAsOf||
     assessedAt-frequency.issuedAsOf>maxLag||
     !Array.isArray(frequency.horizons)||frequency.horizons.length!==3||
     !Array.isArray(ewma.horizons)||ewma.horizons.length!==3)
    throw Error('Mismatched, stale or untrusted offline model inputs');
  const horizons=expected.map((h,i):AgreementHorizon=>{
    const f=frequency.horizons[i],e=ewma.horizons[i];
    validateHorizon(f,e,h);
    let status:AgreementStatus='ABSTAIN_INSUFFICIENT';
    let direction:'UP'|'DOWN'|null=null;
    let absoluteDisagreement:number|null=null;
    let probabilityRange:[number,number]|null=null;
    if(f.probabilityUp!==null&&e.probabilityUp!==null){
      const a=f.probabilityUp,b=e.probabilityUp;
      absoluteDisagreement=Math.abs(a-b);
      probabilityRange=[Math.min(a,b),Math.max(a,b)];
      const bothUp=a>0.5+margin&&b>0.5+margin;
      const bothDown=a<0.5-margin&&b<0.5-margin;
      if(absoluteDisagreement>maxDiff || (a-0.5)*(b-0.5)<0){
        status='ABSTAIN_CONFLICT';
      }else if(bothUp){status='CONSENSUS_UP_RESEARCH_ONLY';direction='UP';}
      else if(bothDown){status='CONSENSUS_DOWN_RESEARCH_ONLY';direction='DOWN';}
      else status='ABSTAIN_UNCERTAIN';
    }
    return {horizon:h,status,direction,frequencyProbability:f.probabilityUp,
      ewmaProbability:e.probabilityUp,absoluteDisagreement,probabilityRange,
      frequencySamples:f.samples,ewmaEffectiveSamples:e.effectiveSamples};
  });
  return {mode:'UNVERIFIED_LOCAL_RESEARCH',live:false,authenticated:false,
    persisted:false,alertsEnabled:false,execution:'NONE',ordersSubmitted:0,
    issuedAsOf:frequency.issuedAsOf,assessedAt,identity:{...frequency.identity},horizons};
}
