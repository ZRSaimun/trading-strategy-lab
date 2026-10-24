/** Source-isolated, completed-minute New York close momentum experiment.
 * Hypothesis inspired by Gao et al. (2018); not a replication, live feed, or
 * evidence of profitable CFDs. All signals freeze at the 15:30 NY OPEN.
 * The 15:30–15:59 outcome is observed only AFTER the entry decision.
 */
import type {Bar} from './research.ts';

export const MODEL='ny-close-intraday-momentum-research-v1';
export type StudyConfig={
 instrument:string;provider:string;archiveId:string;archiveSha256:string;
 priceSide:'bid';assumedRoundTripBps:number;
};
export type CloseTrade={
 nyDate:string;entryAt:number;exitAt:number;direction:'LONG'|'SHORT';
 firstHalfHourBps:number;openToEntryBps:number;
 morningRangeBps:number;priorMedianMorningRangeBps:number;
 entry:number;exit:number;grossBps:number;
};
export type CostRow={
 roundTripBps:number;trades:number;winRatePct:number|null;
 averageNetBps:number|null;profitFactor:number|null;
};
export type CloseMomentumStudy={
 engine:typeof MODEL;source:StudyConfig;session:'NY_0930_1600_EQUITIES';
 totalObservedSessions:number;completeSessions:number;
 candidateDays:number;volatilityGatedDays:number;
 rejected:Record<string,number>;trades:CloseTrade[];
 costs:CostRow[];ungatedCosts:CostRow[];
 warnings:string[];
};
const fmt=new Intl.DateTimeFormat('en-GB',{
 timeZone:'America/New_York',hour12:false,hourCycle:'h23',
 year:'numeric',month:'2-digit',day:'2-digit',weekday:'short',hour:'2-digit',minute:'2-digit'
});
function ny(t:number){
 const p=Object.fromEntries(fmt.formatToParts(new Date(t*1000)).map(x=>[x.type,x.value]));
 return {date:p.year+'-'+p.month+'-'+p.day,weekday:p.weekday,minute:Number(p.hour)*60+Number(p.minute)};
}
/** Complete-minute source observations used by the NY regular-session experiment. */
export function isNyRegularSessionMinute(epochSeconds:number):boolean{
 if(!Number.isSafeInteger(epochSeconds)||epochSeconds<0||epochSeconds%60!==0)return false;
 const z=ny(epochSeconds);
 return z.weekday!=='Sat'&&z.weekday!=='Sun'&&z.minute>=9*60+30&&z.minute<16*60;
}
function sign(n:number){return n>0?1:n<0?-1:0}
function median(xs:readonly number[]){
 const v=[...xs].sort((a,b)=>a-b),n=v.length;
 return n%2?v[(n-1)/2]:(v[n/2-1]+v[n/2])/2;
}
function metrics(trades:readonly CloseTrade[],cost:number):CostRow{
 const net=trades.map(t=>t.grossBps-cost),wins=net.filter(x=>x>0),
  loss=net.filter(x=>x<0),sumWins=wins.reduce((a,b)=>a+b,0),
  sumLoss=-loss.reduce((a,b)=>a+b,0);
 return {roundTripBps:cost,trades:net.length,
  winRatePct:net.length?100*wins.length/net.length:null,
  averageNetBps:net.length?net.reduce((a,b)=>a+b,0)/net.length:null,
  profitFactor:sumLoss>0?sumWins/sumLoss:null};
}
function validate(bars:readonly Bar[],config:StudyConfig){
 if(!config||!config.instrument?.trim()||!config.provider?.trim()||
    !/^[a-f0-9]{64}$/.test(config.archiveId)||
    !/^[a-f0-9]{64}$/.test(config.archiveSha256)||
    config.priceSide!=='bid'||!Number.isFinite(config.assumedRoundTripBps)||
    config.assumedRoundTripBps<=0||config.assumedRoundTripBps>1000)
  throw Error('Source identity and strictly positive illustrative cost bps are required');
 if(!Array.isArray(bars)||bars.length<1||bars.length>20000)
  throw Error('Provide 1–20,000 source-isolated one-minute bars');
 let last=-Infinity;
 for(const b of bars){
  if(!Number.isSafeInteger(b.time)||b.time<0||b.time%60!==0||
   b.time<=last||b.observed_minutes!==1||
   ![b.open,b.high,b.low,b.close].every(n=>Number.isFinite(n)&&n>0)||
   b.high<Math.max(b.open,b.close)||b.low>Math.min(b.open,b.close))
    throw Error('Incomplete, non-positive, unordered or malformed one-minute historical bars');
  last=b.time;
 }
}
/** Pre-registered NY equity RTH session hypothesis; never assume CFD sessions
 * have identical opening/closing auctions or financing cutoff.
 * 20 prior *completed* regular sessions define the median volatility gate.
 */
export function studyNyCloseMomentum(bars:readonly Bar[],config:StudyConfig):CloseMomentumStudy{
 validate(bars,config);
 type Day={date:string;minutes:Map<number,Bar>};
 const dayMap=new Map<string,Day>();
 for(const b of bars){
  const z=ny(b.time),slot=z.minute-(9*60+30);
  if(slot<0||slot>=390||z.weekday==='Sat'||z.weekday==='Sun')continue;
  let day=dayMap.get(z.date);
  if(!day){day={date:z.date,minutes:new Map()};dayMap.set(z.date,day)}
  if(day.minutes.has(slot))throw Error('Duplicate New York session minute');
  day.minutes.set(slot,b);
 }
 const days=[...dayMap.values()];
 const rejected:Record<string,number>={};
 const mark=(why:string)=>{rejected[why]=(rejected[why]||0)+1};
 const trainVol:number[]=[];
 const trades:CloseTrade[]=[],ungated:CloseTrade[]=[];
 let lastComplete:Bar[]|null=null,completeSessions=0,candidateDays=0;
 for(const day of days){
  const full=day.minutes.size===390&&
    Array.from({length:390},(_,i)=>day.minutes.get(i)).every(Boolean);
  if(!full){mark('INCOMPLETE_NY_SESSION');lastComplete=null;continue}
  const d=Array.from({length:390},(_,i)=>day.minutes.get(i)!);
  completeSessions++;
  const morning=d.slice(0,30);
  const range=(Math.max(...morning.map(x=>x.high))-
      Math.min(...morning.map(x=>x.low)))/d[0].open*10000;
  if(lastComplete&&trainVol.length>=20){
   const first=(d[29].close-d[0].open)/d[0].open*10000;
   const drift=(d[360].open-lastComplete[389].close)/lastComplete[389].close*10000;
   const dir=sign(first);
   if(dir===0||dir!==sign(drift))mark('EARLY_AND_DAY_MOVE_DISAGREE');
   else{
    candidateDays++;
    // 15:30 open is the only entry eligible after the preceding close.
    const entry=d[360].open,exit=d[389].close;
    const record:CloseTrade={
     nyDate:day.date,entryAt:d[360].time,exitAt:d[389].time+60,
     direction:dir>0?'LONG':'SHORT',firstHalfHourBps:first,
     openToEntryBps:drift,morningRangeBps:range,
     priorMedianMorningRangeBps:median(trainVol),entry,exit,
     grossBps:dir*(exit-entry)/entry*10000,
    };
    ungated.push(record);
    if(range>record.priorMedianMorningRangeBps)trades.push(record);
    else mark('MORNING_VOLATILITY_NOT_ABOVE_PRIOR_20_MEDIAN');
   }
  }else mark('INSUFFICIENT_20_PRIOR_COMPLETE_SESSIONS');
  lastComplete=d;
  trainVol.push(range);
  if(trainVol.length>20)trainVol.shift();
 }
 const costs=[0,config.assumedRoundTripBps,config.assumedRoundTripBps*2,
   config.assumedRoundTripBps*3];
 return {engine:MODEL,source:{...config},session:'NY_0930_1600_EQUITIES',
  totalObservedSessions:days.length,completeSessions,candidateDays,
  volatilityGatedDays:trades.length,rejected,trades,
  costs:costs.map(c=>metrics(trades,c)),
  ungatedCosts:costs.map(c=>metrics(ungated,c)),
  warnings:[
   'Historical BID-only OHLC is not an executable CFD quote or broker profit.',
   'US equity regular hours are a research convention; Nasdaq CFD, Gold and WTI trading hours, auctions, spreads and financing vary.',
   'Entire 390-minute NY regular session required; early closes, partial imports and session gaps are excluded rather than completed synthetically.',
   'Only preceding 20 fully observed NY sessions set the volatility threshold. The last half-hour outcome never determines its own eligibility.',
   'Costs are owner-declared illustrative bps; no broker ask data, intrabar adverse selection, commissions, financing, taxes or contract multipliers are verified.',
   'Exploratory hypothesis and historical sample only: no verified edge, independent holdout, live signal or executable trading recommendation.',
  ]};
}
