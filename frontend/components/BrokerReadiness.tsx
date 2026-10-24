'use client';
import {useEffect,useState} from 'react';

type API=(path:string,init?:RequestInit)=>Promise<any>;
type BrokerInfo={id:string;api_order_support:boolean;integration_status:string};
type Capabilities={status:string;execution_mode:string;quote_verified:boolean;account_linked:boolean;live_orders_enabled:boolean;demo_orders_enabled:boolean;risk_preview_enabled:boolean;brokers:BrokerInfo[];source_url:string};
type Preview={estimated_exposure:number;estimated_loss_if_filled_at_stop:number;risk_budget_cash:number;estimated_risk_percent:number;within_user_risk_budget:boolean;may_execute_real_order:boolean;warnings:string[]};
type BrokerId='Trading212-CFD'|'Trading212-Invest'|'Trading212-StocksISA';
type StressResult=Preview & {stressed_loss_if_filled:number;stressed_risk_percent:number;stressed_loss_within_budget:boolean;assumed_margin_required:number;assumed_margin_covered_by_equity:boolean;assumed_effective_leverage:number;within_user_leverage_cap:boolean;all_hypothetical_limits_pass:boolean};
type Inputs={broker:BrokerId;symbol:string;direction:'BUY'|'SELL';entry_price:number;stop_price:number;quantity:number;point_value:number;estimated_total_cost:number;account_equity:number;risk_budget_percent:number;price_source:'UNVERIFIED USER INPUT'|'HISTORICAL BID'};
// Avoid displaying a nonzero tiny loss or margin as 0.00.
const precise=(v:number)=>v!==0&&Math.abs(v)<0.0001?v.toExponential(6):v.toLocaleString('en-GB',{maximumSignificantDigits:12});
const DEFAULTS:Inputs={broker:'Trading212-CFD',symbol:'XAUUSD',direction:'BUY',entry_price:100,stop_price:98,quantity:1,point_value:1,estimated_total_cost:2,account_equity:1000,risk_budget_percent:1,price_source:'UNVERIFIED USER INPUT'};
const FIELDS:Array<[keyof Pick<Inputs,'entry_price'|'stop_price'|'quantity'|'point_value'|'estimated_total_cost'|'account_equity'|'risk_budget_percent'>,string]>=[
 ['entry_price','Hypothetical entry price'],['stop_price','Hypothetical protective stop price'],
 ['quantity','Illustrative position quantity'],['point_value','P&L per price point per unit (account currency)'],
 ['estimated_total_cost','Estimated total trading costs (account currency)'],
 ['account_equity','Illustrative account equity (same currency)'],['risk_budget_percent','Maximum planned risk (% of equity)'],
];
export default function BrokerReadiness({api,pages}:{api:API;pages:boolean}){
 const [caps,setCaps]=useState<Capabilities|null>(null),[error,setError]=useState('');
 const [inputs,setInputs]=useState<Inputs>(DEFAULTS),[preview,setPreview]=useState<Preview|null>(null),[busy,setBusy]=useState(false);
 const [stressExit,setStressExit]=useState(95),[marginPercent,setMarginPercent]=useState(10),[maxLeverage,setMaxLeverage]=useState(2);
 const [stressResult,setStressResult]=useState<StressResult|null>(null),[stressBusy,setStressBusy]=useState(false);
 useEffect(()=>{if(pages)return;let active=true;api('/broker/capabilities').then((v:Capabilities)=>{if(active){setCaps(v);setError('')}}).catch(e=>{if(active)setError(e.message||String(e))});return()=>{active=false}},[api,pages]);
 const changeNumber=(key:typeof FIELDS[number][0],raw:string)=>{setInputs(old=>({...old,[key]:Number(raw)}));setPreview(null);setStressResult(null)};
 async function calculate(e:React.FormEvent<HTMLFormElement>){e.preventDefault();setError('');setBusy(true);setPreview(null);try{const result=await api('/broker/order-risk-preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(inputs)});setPreview(result)}catch(e){setError(e instanceof Error?e.message:String(e))}finally{setBusy(false)}}
 async function calculateStress(e:React.FormEvent<HTMLFormElement>){e.preventDefault();setError('');setStressBusy(true);setStressResult(null);try{const result=await api('/broker/stress-preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...inputs,stressed_exit_price:stressExit,margin_requirement_percent:marginPercent,max_leverage:maxLeverage})});setStressResult(result)}catch(e){setError(e instanceof Error?e.message:String(e))}finally{setStressBusy(false)}}
 return <section className="panel research-panel">
  <span className="eyebrow">ACCOUNT CONNECTION · CAPABILITY STATUS · ZERO EXECUTION</span>
  <h2>Broker Readiness &amp; Risk Preview</h2>
  <p>This screen checks what our site can actually support. It does not connect a brokerage account or enable orders. Do not enter a real account password or API key here.</p>
  {pages?<p role="status">The browser-local version has no authenticated broker-service API. Open your private server to see the latest integration status.</p>:<>
   {error&&<p role="alert" className="error">{error}</p>}
   <div className="market-strip"><div><small>BROKER CONNECTION</small><strong>{caps?.status||'Checking…'}</strong></div><div><small>LIVE ORDER API</small><strong>{caps?.live_orders_enabled?'AVAILABLE':'NOT CONNECTED'}</strong></div><div><small>DEMO ORDER API</small><strong>{caps?.demo_orders_enabled?'AVAILABLE':'NOT CONNECTED'}</strong></div><div><small>RISK PREVIEW</small><strong>{caps?.risk_preview_enabled?'AVAILABLE':'UNAVAILABLE'}</strong></div></div>
   <p><strong>API-supported account types:</strong> Trading 212 Invest and Stocks ISA offer documented order endpoints, but neither is connected to this website. Its CFD account type is not supported by the documented Public API.</p>
   {caps?.brokers.map(b=><p key={b.id}><strong>{b.id}</strong> — {b.integration_status}</p>)}
   <p><a href="https://docs.trading212.com/api" target="_blank" rel="noreferrer">Official Trading 212 Public API documentation ↗</a></p>
   <h3>Illustrative order-risk calculation</h3>
   <p>Use numbers you choose yourself. The result is NOT an executable quote, order, position recommendation or approval to trade. A stop can slip or gap, so actual loss may be greater.</p>
   <form onSubmit={calculate} className="backtest-settings">
    <label>Broker / account type<select value={inputs.broker} onChange={e=>{setInputs(s=>({...s,broker:e.target.value as BrokerId}));setPreview(null);setStressResult(null)}}><option value="Trading212-CFD">Trading 212 CFD — API orders unsupported</option><option value="Trading212-Invest">Trading 212 Invest — unconnected</option><option value="Trading212-StocksISA">Trading 212 Stocks ISA — unconnected</option></select></label>
    <label>Exact instrument symbol<input value={inputs.symbol} maxLength={50} required onChange={e=>{setInputs(s=>({...s,symbol:e.target.value}));setPreview(null);setStressResult(null)}}/></label>
    <label>Side<select value={inputs.direction} onChange={e=>{setInputs(s=>({...s,direction:e.target.value as 'BUY'|'SELL'}));setPreview(null);setStressResult(null)}}><option>BUY</option><option>SELL</option></select></label>
    <label>Price source<select value={inputs.price_source} onChange={e=>{setInputs(s=>({...s,price_source:e.target.value as Inputs['price_source']}));setPreview(null);setStressResult(null)}}><option>UNVERIFIED USER INPUT</option><option>HISTORICAL BID</option></select></label>
    {FIELDS.map(([key,label])=><label key={key}>{label}<input type="number" step="any" required value={inputs[key]} onChange={e=>changeNumber(key,e.target.value)}/></label>)}
    <button className="primary" disabled={!caps?.risk_preview_enabled||busy}>{busy?'Checking…':'Calculate risk only · no order'}</button>
   </form>
   <h3>Adverse stop-gap, margin &amp; leverage scenario</h3>
   <p>Stress test the same hypothetical order against a worse-than-stop exit, assumed initial margin and a leverage cap. This is not a worst-case loss or a broker margin check. No orders are sent.</p>
   <form onSubmit={calculateStress} className="backtest-settings">
    <label>Stressed fill price (worse than stop)<input type="number" step="any" min="0.00000001" required value={stressExit} onChange={e=>{setStressExit(Number(e.target.value));setStressResult(null)}}/></label>
    <label>Assumed margin requirement (%)<input type="number" step="any" min="0.00000001" max="100" required value={marginPercent} onChange={e=>{setMarginPercent(Number(e.target.value));setStressResult(null)}}/></label>
    <label>Maximum assumed leverage (×)<input type="number" step="any" min="0.00000001" max="100" required value={maxLeverage} onChange={e=>{setMaxLeverage(Number(e.target.value));setStressResult(null)}}/></label>
    <button className="primary" disabled={!caps?.risk_preview_enabled||stressBusy}>{stressBusy?'Checking scenario…':'Stress test · no order'}</button>
   </form>
   {stressResult&&<div className="journal-entry" role="status"><h3>Hypothetical stressed scenario</h3>
    <p>Stressed fill loss: <strong>{precise(stressResult.stressed_loss_if_filled)}</strong> account currency units · {precise(stressResult.stressed_risk_percent)}% of assumed equity.</p>
    <p>Assumed margin required: {precise(stressResult.assumed_margin_required)} · Effective leverage: {precise(stressResult.assumed_effective_leverage)}×.</p>
    <p>Stressed loss within budget: {stressResult.stressed_loss_within_budget?'YES':'NO'} · Margin covered: {stressResult.assumed_margin_covered_by_equity?'YES':'NO'} · Leverage within cap: {stressResult.within_user_leverage_cap?'YES':'NO'}.</p>
    <p><strong>{stressResult.all_hypothetical_limits_pass?'All illustrative checks passed (NOT an order approval)':'One or more illustrative risk checks failed'}</strong> · Live and paper execution: DISABLED</p>
    <ul>{stressResult.warnings.map((w,i)=><li key={i}>{w}</li>)}</ul>
   </div>}
   {preview&&<div className="journal-entry" role="status"><h3>Research-only risk estimate</h3>
    <p>Estimated loss if filled at stop: <strong>{precise(preview.estimated_loss_if_filled_at_stop)}</strong> account currency units</p>
    <p>Chosen risk budget: {precise(preview.risk_budget_cash)} · Estimated risk: {precise(preview.estimated_risk_percent)}%</p>
    <p>Estimated notional: {precise(preview.estimated_exposure)} (only if point value and conversion are correct)</p>
    <p><strong>{preview.within_user_risk_budget?'Within your illustrative budget':'Exceeds your illustrative risk budget'}</strong> · Live execution: NOT AUTHORISED</p>
    <ul>{preview.warnings.map((w,i)=><li key={i}>{w}</li>)}</ul>
   </div>}
  </>}
 </section>
}