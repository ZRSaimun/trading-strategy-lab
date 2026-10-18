// Observed imported candles only. No gap filling or forward-looking windows.
export type IndicatorBar={time:number;open:number;high:number;low:number;close:number;volume:number|null};
export type Study='SMA 20'|'EMA 20'|'Bollinger 20'|'VWAP'|'RSI 14'|'ATR 14'|'MACD'|'Volume';
export const STUDIES:Study[]=['SMA 20','EMA 20','Bollinger 20','VWAP','RSI 14','ATR 14','MACD','Volume'];
export type Values=(number|null)[];
export function sma(values:number[],period:number):Values{
 if(!Number.isInteger(period)||period<1)throw Error('Positive integer period required');
 let sum=0;return values.map((v,i)=>{sum+=v;if(i>=period)sum-=values[i-period];return i>=period-1?sum/period:null});
}
export function ema(values:number[],period:number):Values{
 const seed=sma(values,period);let previous:number|null=null;
 return values.map((v,i)=>{if(i<period-1)return null;previous=previous===null?seed[i]!:(v-previous)*2/(period+1)+previous;return previous});
}
function wilder(values:number[],period:number):Values{
 const seed=sma(values,period);let previous:number|null=null;
 return values.map((v,i)=>{if(i<period-1)return null;previous=previous===null?seed[i]!:(previous*(period-1)+v)/period;return previous});
}
const londonDate=new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/London',year:'numeric',month:'2-digit',day:'2-digit'});
export function volumeAvailable(bars:IndicatorBar[],classification:string){return (classification==='tick'||classification==='exchange')&&bars.length>0&&bars.every(b=>b.volume!==null&&Number.isFinite(b.volume)&&b.volume>=0)}
export function calculateIndicators(bars:IndicatorBar[],classification:string){
 const closes=bars.map(b=>b.close),mean=sma(closes,20),average=ema(closes,20);
 // Sliding centered sum avoids subtracting large squared prices for variance.
 const upper:Values=[],lower:Values=[];
 for(let i=0;i<bars.length;i++){
  if(mean[i]===null){upper.push(null);lower.push(null);continue}
  let squares=0;for(let j=i-19;j<=i;j++)squares+=(closes[j]-mean[i]!)**2;
  const deviation=Math.sqrt(squares/20)*2;upper.push(mean[i]!+deviation);lower.push(mean[i]!-deviation);
 }
 const gains:number[]=[],losses:number[]=[];
 for(let i=1;i<bars.length;i++){const change=closes[i]-closes[i-1];gains.push(Math.max(change,0));losses.push(Math.max(-change,0))}
 const gain=wilder(gains,14),loss=wilder(losses,14);
 const rsi:Values=bars.map((_,i)=>i<14?null:loss[i-1]===0?(gain[i-1]===0?50:100):100-100/(1+gain[i-1]!/loss[i-1]!));
 const atr=wilder(bars.map((b,i)=>i===0?b.high-b.low:Math.max(b.high-b.low,Math.abs(b.high-closes[i-1]),Math.abs(b.low-closes[i-1]))),14);
 const fast=ema(closes,12),slow=ema(closes,26),macd:Values=closes.map((_,i)=>slow[i]===null?null:fast[i]!-slow[i]!);
 const validMacd=macd.slice(25) as number[],signalSeed=ema(validMacd,9);
 const signal:Values=closes.map((_,i)=>i<25?null:signalSeed[i-25]);
 const histogram:Values=closes.map((_,i)=>signal[i]==null?null:macd[i]!-signal[i]!);
 const validVolume=volumeAvailable(bars,classification);
 let day='',weighted=0,weight=0,missing=false;
 const vwap:Values=bars.map(b=>{const next=londonDate.format(b.time*1000);if(next!==day){day=next;weighted=0;weight=0;missing=false}if(classification!=='tick'&&classification!=='exchange')return null;if(b.volume===null||!Number.isFinite(b.volume)||b.volume<0)missing=true;if(missing)return null;weighted+=(b.high+b.low+b.close)/3*b.volume!;weight+=b.volume!;return weight>0?weighted/weight:null});
 return {sma:mean,ema:average,upper,lower,vwap,rsi,atr,macd,signal,histogram,validVolume};
}
