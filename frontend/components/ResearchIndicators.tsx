'use client';
import {LineSeries,HistogramSeries,type IChartApi,type UTCTimestamp,type ISeriesApi} from 'lightweight-charts';
import {calculateIndicators,STUDIES,type Study,type IndicatorBar,type Values} from '../lib/indicators';
export {STUDIES};
export type {Study};
export function installIndicators(chart:IChartApi,bars:IndicatorBar[],volumeType:string,enabled:Study[]){
 if(!enabled.length||!bars.length)return ()=>{};
 const values=calculateIndicators(bars,volumeType);
  const added:(ISeriesApi<'Line'>|ISeriesApi<'Histogram'>)[]=[];
  let pane=0;
  function line(title:string,data:Values,color:string,index=0){
   const s=chart!.addSeries(LineSeries,{title,color,lineWidth:1,priceLineVisible:false,lastValueVisible:true,crosshairMarkerVisible:true},index);
   s.setData(data.map((value,i)=>value===null?{time:bars[i].time as UTCTimestamp}:{time:bars[i].time as UTCTimestamp,value}));added.push(s);
  }
  if(enabled.includes('SMA 20'))line('SMA 20',values.sma,'#db9c22');
  if(enabled.includes('EMA 20'))line('EMA 20',values.ema,'#338be0');
  if(enabled.includes('Bollinger 20')){line('BB upper',values.upper,'#9973e5');line('BB middle',values.sma,'#a296bd');line('BB lower',values.lower,'#9973e5')}
  if(enabled.includes('VWAP')&&values.validVolume)line('London daily VWAP',values.vwap,'#db62b2');
  if(enabled.includes('Volume')&&values.validVolume){const s=chart.addSeries(HistogramSeries,{title:volumeType==='tick'?'Tick volume':'Exchange volume',priceFormat:{type:'volume'},priceLineVisible:false},++pane);s.setData(bars.map(b=>({time:b.time as UTCTimestamp,value:b.volume!,color:b.close>=b.open?'#2dba9577':'#e45b7277'})));added.push(s)}
  if(enabled.includes('RSI 14')){line('RSI 14',values.rsi,'#9973e5',++pane)}
  if(enabled.includes('ATR 14'))line('ATR 14',values.atr,'#d3952c',++pane);
  if(enabled.includes('MACD')){
   ++pane;line('MACD 12/26',values.macd,'#338be0',pane);line('Signal 9',values.signal,'#dc8a30',pane);
   const s=chart.addSeries(HistogramSeries,{title:'MACD histogram',priceLineVisible:false},pane);s.setData(values.histogram.map((value,i)=>value===null?{time:bars[i].time as UTCTimestamp}:{time:bars[i].time as UTCTimestamp,value,color:value>=0?'#2dba9577':'#e45b7277'}));added.push(s);
  }
  chart.panes().forEach((p,i)=>p.setStretchFactor(i===0?5:1.5));
  return ()=>{for(const s of added)chart.removeSeries(s)};

}
