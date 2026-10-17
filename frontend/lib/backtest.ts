import type {Bar} from './research.ts';

export const ENGINE='candle-simulator-v1';
export const STRATEGIES=[
 {id:'A',name:'A · Range-break baseline',version:'range-break-v1',definition:'First close outside the preceding N-bar range. Research baseline; not a reconstruction of your original strategy.'},
 {id:'B',name:'B · Sweep / shift / retest',version:'sweep-shift-retest-v1',definition:'Sweep and same-bar reclaim of the prior range, then ATR displacement through pre-sweep structure, then a later defended retest.'},
 {id:'C',name:'C · CRT range reclaim',version:'crt-range-v1',definition:'Sweep and same-bar reclaim of the preceding N-bar reference range. Entry at a later open.'},
 {id:'D',name:'D · Displacement / FVG retest',version:'fvg-retest-v1',definition:'ATR displacement creating a three-candle FVG and closing beyond the preceding three-bar structure, then a later defended retest.'},
 {id:'E',name:'E · Sweep + shift + FVG retest',version:'combined-research-v1',definition:'Strategy B plus a directional FVG on the displacement confirmation bar. Not assumed superior.'},
] as const;
export type StrategyId=typeof STRATEGIES[number]['id'];
export type Config={lookback:number;atrPeriod:number;displacement:number;expiry:number;rr:number;spread:number;slippage:number;commission:number;pointValue:number;capital:number;riskPercent:number;barSeconds:number;maxHold:number};
export const DEFAULTS:Config={lookback:20,atrPeriod:14,displacement:0.6,expiry:12,rr:2,spread:0.4,slippage:0.1,commission:0,pointValue:1,capital:10000,riskPercent:0.5,barSeconds:300,maxHold:48};
export type Candidate={index:number;direction:1|-1;stop:number;level:number;evidence:number[];classification:string};
export type Trade={id:string;strategy:StrategyId;ruleVersion:string;candidateAt:number;entryAt:number;exitAt:number;direction:'BUY'|'SELL';entry:number;stop:number;target:number;exit:number;units:number;pnl:number;r:number;costs:number;reason:string;evidence:number[];status:'HYPOTHETICAL CLOSED';verification:'SIMULATED OHLC ONLY'};
export type Metrics={trades:number;winRate:number|null;profitFactor:number|null;avgWin:number;avgLoss:number;expectancy:number;averageR:number;netPnl:number;netReturn:number;maxDrawdown:number;maxDrawdownPercent:number;rejected:number;wilson95:[number,number]|null};
export type Report={engine:string;strategy:StrategyId;ruleVersion:string;config:Config;start:number;end:number;bars:number;trades:Trade[];metrics:Metrics;equity:{time:number;balance:number;mark:number}[];rejections:Record<string,number>;warnings:string[];status:'HISTORICAL SIMULATION'};
function checkConfig(c:Config){
 if(Object.values(c).some(x=>!Number.isFinite(x)))throw Error('All settings must be finite numbers');
 for(const k of ['lookback','atrPeriod','expiry','barSeconds','maxHold'] as const)if(!Number.isInteger(c[k])||c[k]<1)throw Error(`${k} must be a positive integer`);
 if(c.lookback<3||c.lookback>500||c.atrPeriod>500||c.expiry>500||c.maxHold>10000)throw Error('Settings exceed research limits');
 if(c.rr<2||c.rr>20||c.displacement<0||c.spread<0||c.slippage<0||c.commission<0||c.pointValue<=0||c.capital<=0||c.riskPercent<=0||c.riskPercent>5)throw Error('Invalid risk/cost settings; minimum net RR is 2 and risk is at most 5%');
}
function validateBars(bars:Bar[],seconds:number){
 if(bars.length<5||bars.length>100000)throw Error('Backtest requires 5–100,000 candles');
 bars.forEach((b,i)=>{if(b.observed_minutes!==seconds/60)throw Error('Incomplete aggregate candles: choose a timeframe with complete source minutes or import contiguous data');if(![b.time,b.open,b.high,b.low,b.close].every(Number.isFinite)||b.low>Math.min(b.open,b.close)||b.high<Math.max(b.open,b.close)||b.low>b.high||(i>0&&b.time-bars[i-1].time<seconds))throw Error('Invalid, overlapping or unordered candles')});
}
function range(bars:Bar[],start:number,end:number){let high=-Infinity,low=Infinity;for(let k=start;k<end;k++){high=Math.max(high,bars[k].high);low=Math.min(low,bars[k].low)}return {high,low}}
function atr(bars:Bar[],i:number,n:number){let sum=0;for(let k=i-n;k<i;k++){const b=bars[k],prev=bars[k-1]?.close??b.open;sum+=Math.max(b.high-b.low,Math.abs(b.high-prev),Math.abs(b.low-prev))}return sum/n}

// Single forward pass. Stored reference levels never change using later candles.
export function candidates(bars:Bar[],id:StrategyId,c:Config):Candidate[]{
 checkConfig(c);const out:Candidate[]=[];
 type Pending={direction:1|-1;stop:number;level:number;shift:number;created:number;stage:'SHIFT'|'RETEST';evidence:number[]};
 let pending:Pending|null=null;
 for(let i=Math.max(c.lookback,c.atrPeriod,3);i<bars.length;i++){
  const b=bars[i];if(b.time-bars[i-1].time!==c.barSeconds){pending=null;continue}
  // Require a contiguous reference window. Unknown calendar gaps are never treated as normal bars.
  if(bars[i].time-bars[i-Math.max(c.lookback,c.atrPeriod)].time!==Math.max(c.lookback,c.atrPeriod)*c.barSeconds){pending=null;continue}
  const ref=range(bars,i-c.lookback,i),structure=range(bars,i-3,i),a=atr(bars,i,c.atrPeriod);
  const bullGap=i>=2&&b.low>bars[i-2].high,bearGap=i>=2&&b.high<bars[i-2].low;
  const emit=(d:1|-1,stop:number,level:number,evidence:number[],classification:string)=>out.push({index:i,direction:d,stop,level,evidence,classification});
  if(id==='A'){
   if(b.close>ref.high)emit(1,ref.low,ref.high,[bars[i-c.lookback].time,b.time],'UNCONFIRMED FIRST BREAK BASELINE');
   else if(b.close<ref.low)emit(-1,ref.high,ref.low,[bars[i-c.lookback].time,b.time],'UNCONFIRMED FIRST BREAK BASELINE');
   continue;
  }
  if(pending){
   const p=pending;
   if(i-p.created>c.expiry||(p.direction===1?b.low<=p.stop:b.high>=p.stop)){pending=null}
   else if(p.stage==='SHIFT'){
    const shift=p.direction===1?b.close>p.shift&&b.close-b.open>=a*c.displacement:b.close<p.shift&&b.open-b.close>=a*c.displacement;
    if(shift&&(id!=='E'||(p.direction===1?bullGap:bearGap))){p.stage='RETEST';p.level=p.shift;p.evidence.push(b.time);continue}
   }else if(p.direction===1?b.low<=p.level&&b.close>p.level:b.high>=p.level&&b.close<p.level){emit(p.direction,p.stop,p.level,[...p.evidence,b.time],'DEFENDED RETEST');pending=null;continue}
   if(pending)continue;
  }
  if(id==='D'){
   if(bullGap&&b.close>structure.high&&b.close-b.open>=a*c.displacement)pending={direction:1,stop:bars[i-2].low,level:b.low,shift:structure.high,created:i,stage:'RETEST',evidence:[bars[i-2].time,bars[i-1].time,b.time]};
   else if(bearGap&&b.close<structure.low&&b.open-b.close>=a*c.displacement)pending={direction:-1,stop:bars[i-2].high,level:b.high,shift:structure.low,created:i,stage:'RETEST',evidence:[bars[i-2].time,bars[i-1].time,b.time]};
   continue;
  }
  const downSweep=b.low<ref.low&&b.close>ref.low,upSweep=b.high>ref.high&&b.close<ref.high;
  // Two-sided outside bars do not give an unambiguous directional candidate.
  if(downSweep===upSweep)continue;
  const d:1|-1=downSweep?1:-1,stop=downSweep?b.low:b.high,level=downSweep?ref.low:ref.high;
  if(id==='C')emit(d,stop,level,[bars[i-c.lookback].time,b.time],'RANGE SWEEP AND RECLAIM');
  else pending={direction:d,stop,level,shift:d===1?structure.high:structure.low,created:i,stage:'SHIFT',evidence:[bars[i-c.lookback].time,b.time]};
 }
 return out;
}

export function summarize(trades:Trade[],equity:Report['equity'],capital:number,rejected:number):Metrics{
 const wins=trades.filter(t=>t.pnl>0),losses=trades.filter(t=>t.pnl<0),positive=wins.reduce((s,t)=>s+t.pnl,0),negative=-losses.reduce((s,t)=>s+t.pnl,0),n=trades.length;
 let peak=capital,dd=0,ddp=0;for(const p of equity){peak=Math.max(peak,p.mark);dd=Math.max(dd,peak-p.mark);ddp=Math.max(ddp,peak>0?(peak-p.mark)/peak*100:0)}
 const net=trades.reduce((s,t)=>s+t.pnl,0),p=n?wins.length/n:0,z=1.96,den=1+z*z/Math.max(n,1),centre=(p+z*z/(2*Math.max(n,1)))/den,half=z*Math.sqrt(p*(1-p)/Math.max(n,1)+z*z/(4*Math.max(n,1)**2))/den;
 return {trades:n,winRate:n?p*100:null,profitFactor:negative?positive/negative:null,avgWin:wins.length?positive/wins.length:0,avgLoss:losses.length?-negative/losses.length:0,expectancy:n?net/n:0,averageR:n?trades.reduce((s,t)=>s+t.r,0)/n:0,netPnl:net,netReturn:net/capital*100,maxDrawdown:dd,maxDrawdownPercent:ddp,rejected,wilson95:n?[Math.max(0,centre-half)*100,Math.min(1,centre+half)*100]:null};
}
export function backtest(bars:Bar[],id:StrategyId,c:Config):Report{
 checkConfig(c);validateBars(bars,c.barSeconds);const strategy=STRATEGIES.find(s=>s.id===id);if(!strategy)throw Error('Unknown strategy');
 const byIndex=new Map(candidates(bars,id,c).map(x=>[x.index,x]));
 const trades:Trade[]=[],equity:Report['equity']=[],rejections:Record<string,number>={};
 const reject=(reason:string)=>{rejections[reason]=(rejections[reason]||0)+1};
 const friction=c.spread/2+c.slippage;
 let balance=c.capital;
 type Position={candidate:Candidate;entry:number;entryIndex:number;target:number;units:number;risk:number};let position:Position|null=null;
 for(let i=0;i<bars.length;i++){
  const b=bars[i];const signal=byIndex.get(i-1);
  if(signal){
   if(position)reject('Position already open');
   else if(b.time-bars[i-1].time!==c.barSeconds)reject('Gap before entry');
   else if(balance<=0)reject('Capital exhausted');
   else{
    const entry=b.open+signal.direction*friction;
    const distance=signal.direction*(entry-signal.stop);
    const risk=distance*c.pointValue+friction*c.pointValue+2*c.commission;
    if(signal.direction*(b.open-signal.stop)<=0||distance<=0||risk<=0)reject('Entry beyond invalidation');
    else{const units=balance*c.riskPercent/100/risk;const target=entry+signal.direction*(risk*c.rr/c.pointValue+friction+2*c.commission/c.pointValue);position={candidate:signal,entry,entryIndex:i,target,units,risk}}
   }
  }
  if(position){
   const p=position,d=p.candidate.direction,stop=p.candidate.stop;
   let raw:number|undefined,reason='';
   if(i>p.entryIndex&&b.time-bars[i-1].time!==c.barSeconds){raw=d===1?Math.min(b.open,stop):Math.max(b.open,stop);reason='Unknown gap: conservative stop or worse'}
   else if(i>p.entryIndex&&(d===1?b.open<=stop:b.open>=stop)){raw=b.open;reason='Gap through stop'}
   else if(i>p.entryIndex&&(d===1?b.open>=p.target:b.open<=p.target)){raw=p.target;reason='Target (gap improvement ignored)'}
   else{
    const stopped=d===1?b.low<=stop:b.high>=stop,targeted=d===1?b.high>=p.target:b.low<=p.target;
    if(stopped){raw=stop;reason=targeted?'Stop first: ambiguous OHLC':'Stop'}
    else if(targeted){raw=p.target;reason='Target'}
    else if(i-p.entryIndex>=c.maxHold){raw=b.close;reason='Maximum holding period'}
    else if(i===bars.length-1){raw=b.close;reason='End of test liquidation'}
   }
   if(raw!==undefined){
    const exit=raw-d*friction;
    const pnl=(d*(exit-p.entry)*c.pointValue-2*c.commission)*p.units;
    balance+=pnl;
    trades.push({id:`${id}-${bars[p.candidate.index].time}-${b.time}`,strategy:id,ruleVersion:strategy.version,candidateAt:bars[p.candidate.index].time+c.barSeconds,entryAt:bars[p.entryIndex].time,exitAt:b.time+c.barSeconds,direction:d===1?'BUY':'SELL',entry:p.entry,stop,target:p.target,exit,units:p.units,pnl,r:pnl/(p.risk*p.units),costs:(2*friction*c.pointValue+2*c.commission)*p.units,reason,evidence:p.candidate.evidence,status:'HYPOTHETICAL CLOSED',verification:'SIMULATED OHLC ONLY'});
    position=null;
   }
  }
  const mark=position?balance+(position.candidate.direction*(b.close-position.entry)*c.pointValue-friction*c.pointValue-2*c.commission)*position.units:balance;
  equity.push({time:b.time+c.barSeconds,balance,mark});
 }
 if(byIndex.has(bars.length-1))reject('No next candle for entry');
 const count=Object.values(rejections).reduce((s,n)=>s+n,0);
 return {engine:ENGINE,strategy:id,ruleVersion:strategy.version,config:{...c},start:bars[0].time,end:bars.at(-1)!.time+c.barSeconds,bars:bars.length,trades,metrics:summarize(trades,equity,c.capital,count),equity,rejections,warnings:['Research definitions are approximations, not verified versions of your original strategy.','OHLC execution approximation; no bid/ask, exchange calendar, corporate actions, contract expiry or intrabar path data.','Drawdown uses close-marked equity; intrabar drawdown can be larger.','Costs and point value are user assumptions, not verified broker specifications.','Small or optimized samples do not establish profitability. Wilson interval assumes independent trades.'],status:'HISTORICAL SIMULATION'};
}
export function compare(bars:Bar[],config:Config){return STRATEGIES.map(s=>backtest(bars,s.id,config))}
