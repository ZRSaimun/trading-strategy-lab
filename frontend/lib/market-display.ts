// Display-only identities. Never map these to CSV series or infer feed entitlement.
export const DISPLAY_MARKETS=[
 {id:'gold',name:'Gold · XAUUSD',symbol:'OANDA:XAUUSD',type:'OANDA OTC gold / USD quote',note:'Broker-specific OTC feed; not a universal executable gold price.'},
 {id:'nasdaq',name:'Nasdaq-100 · cash index',symbol:'NASDAQ:NDX',type:'Nasdaq-100 cash index',note:'Cash index, not NQ futures or broker CFDs. May be delayed or restricted in widgets.'},
 {id:'silver',name:'Silver · XAGUSD',symbol:'OANDA:XAGUSD',type:'OANDA OTC silver / USD quote',note:'Broker-specific OTC feed.'},
 {id:'oil',name:'WTI · continuous futures',symbol:'NYMEX:CL1!',type:'NYMEX WTI continuous front-month display series',note:'Continuous rolled series, NOT an individual expiring contract. Not enabled for our simulator.'},
 {id:'nikkei',name:'Nikkei 225 · cash index',symbol:'TVC:NI225',type:'Nikkei 225 index display',note:'Not Japan 225 broker CFD or Nikkei futures.'},
 {id:'nvda',name:'NVIDIA · NVDA',symbol:'NASDAQ:NVDA',type:'NASDAQ US equity',note:'Exchange display may be delayed; read the chart status.'},
 {id:'tsla',name:'Tesla · TSLA',symbol:'NASDAQ:TSLA',type:'NASDAQ US equity',note:'Exchange display may be delayed; read the chart status.'},
 {id:'sp500',name:'S&P 500 · cash index',symbol:'SP:SPX',type:'S&P 500 cash index',note:'Not ES futures or an ETF; widget availability is provider-controlled.'},
 {id:'voo',name:'Vanguard S&P 500 ETF · VOO',symbol:'AMEX:VOO',type:'US-listed VOO ETF',note:'ETF tracking the S&P 500, not the index itself.'},
 {id:'dxy',name:'US Dollar Index · DXY',symbol:'TVC:DXY',type:'Dollar index display series',note:'Provider index reference, not a broker executable quote.'},
 {id:'us2y',name:'US 2-year Treasury yield',symbol:'TVC:US02Y',type:'US two-year benchmark yield',note:'Yield in percent, not a bond price.'},
 {id:'us10y',name:'US 10-year Treasury yield',symbol:'TVC:US10Y',type:'US ten-year benchmark yield',note:'Yield in percent, not a bond price.'},
 {id:'vix',name:'VIX · volatility index',symbol:'CBOE:VIX',type:'CBOE VIX index',note:'Index, not VIX futures; may be delayed or restricted.'},
 {id:'eurusd',name:'Euro / US Dollar',symbol:'OANDA:EURUSD',type:'OANDA OTC EUR/USD',note:'Broker-specific OTC FX feed.'},
 {id:'gbpusd',name:'British Pound / US Dollar',symbol:'OANDA:GBPUSD',type:'OANDA OTC GBP/USD',note:'Broker-specific OTC FX feed.'},
 {id:'bitcoin',name:'Bitcoin / US Dollar',symbol:'COINBASE:BTCUSD',type:'Coinbase BTC/USD spot',note:'Exchange-specific spot USD pair, not BTC/USDT or a CFD.'},
 {id:'ethereum',name:'Ethereum / US Dollar',symbol:'COINBASE:ETHUSD',type:'Coinbase ETH/USD spot',note:'Exchange-specific spot USD pair, not ETH/USDT or a CFD.'},
 {id:'nq',name:'Nasdaq-100 · continuous NQ futures',symbol:'CME_MINI:NQ1!',type:'CME E-mini Nasdaq-100 continuous front-month display series',note:'Not the cash index or an individual futures expiry. Not enabled for our simulator.'},
] as const;
export function widgetConfig(symbol:string,light:boolean,interval:string){
 if(!DISPLAY_MARKETS.some(m=>m.symbol===symbol))throw Error('Unknown display symbol');
 if(!['1','3','5','15','30','60','120','240','D','W','M'].includes(interval))throw Error('Unsupported display interval');
 return {autosize:true,symbol,interval,timezone:'Europe/London',theme:light?'light':'dark',style:'1',locale:'en',allow_symbol_change:false,hide_side_toolbar:false,hide_top_toolbar:false,calendar:false,save_image:false,withdateranges:true,support_host:'https://www.tradingview.com'};
}
// Same remote iframe route and encoded configuration used by the official embed loader.
// A cross-origin remote iframe can keep its own origin without sharing the host's storage.
export function widgetURL(symbol:string,light:boolean,interval:string){
 const config=widgetConfig(symbol,light,interval);
 return 'https://www.tradingview-widget.com/embed-widget/advanced-chart/?locale=en#'+encodeURIComponent(JSON.stringify(config));
}
