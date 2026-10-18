import {test} from 'node:test';
import assert from 'node:assert/strict';
import {DISPLAY_MARKETS,feedOptions,widgetConfig,widgetURL,restoreFeedChoices} from '../lib/market-display.ts';
test('display registry preserves distinct cash, futures and exchange spot identities',()=>{
 const symbols=DISPLAY_MARKETS.map(m=>m.symbol);assert.equal(new Set(symbols).size,symbols.length);
 assert.ok(symbols.includes('NASDAQ:NDX'));assert.ok(symbols.includes('CME_MINI:NQ1!'));assert.ok(symbols.includes('NYMEX:CL1!'));
 assert.match(DISPLAY_MARKETS.find(m=>m.id==='oil')!.note,/NOT an individual/);
 assert.equal(DISPLAY_MARKETS.find(m=>m.id==='bitcoin')!.symbol,'COINBASE:BTCUSD');
});
test('external display configuration rejects arbitrary symbols or script injection and unsupported intervals',()=>{
 assert.throws(()=>widgetURL('</script><script>alert(1)</script>',true,'60'));
 assert.throws(()=>widgetConfig('OANDA:XAUUSD',true,'arbitrary'));
 const config=widgetConfig('OANDA:XAUUSD',true,'60');assert.equal(config.symbol,'OANDA:XAUUSD');assert.equal(config.theme,'light');assert.equal(config.allow_symbol_change,false);assert.equal(config.timezone,'Europe/London');
});
test('remote display frame uses only the pinned provider origin and public configuration',()=>{
 const url=new URL(widgetURL('OANDA:XAUUSD',true,'60'));
 assert.equal(url.origin,'https://www.tradingview-widget.com');assert.equal(url.pathname,'/embed-widget/advanced-chart/');
 const config=JSON.parse(decodeURIComponent(url.hash.slice(1)));assert.equal(config.theme,'light');assert.equal(config.symbol,'OANDA:XAUUSD');
 assert.ok(!url.href.includes('apikey'));assert.equal(widgetConfig('OANDA:XAUUSD',false,'60').theme,'dark');
});

test('all markets and explicit alternatives round-trip to their own provider symbol',()=>{
 for(const market of DISPLAY_MARKETS){const feeds=feedOptions(market.id);assert.equal(feeds[0].symbol,market.symbol);
  for(const feed of feeds){const url=new URL(widgetURL(feed.symbol,true,'60'));const cfg=JSON.parse(decodeURIComponent(url.hash.slice(1)));assert.equal(cfg.symbol,feed.symbol)}
 }
 assert.equal(feedOptions('nasdaq')[0].symbol,'NASDAQ:NDX');assert.equal(feedOptions('nasdaq')[1].symbol,'OANDA:NAS100USD');assert.match(feedOptions('nasdaq')[1].type,/CFD/);
 assert.equal(feedOptions('oil')[0].symbol,'NYMEX:CL1!');assert.match(feedOptions('oil')[1].note,/NOT an individual/);
 assert.throws(()=>feedOptions('unknown-market'));
});

test('remembered feed choices retain exact explicit alternatives and discard null or foreign symbols',()=>{
 assert.deepEqual(restoreFeedChoices(JSON.stringify({nasdaq:'OANDA:NAS100USD',oil:'OANDA:WTICOUSD',gold:'OANDA:XAUUSD'})),{nasdaq:'OANDA:NAS100USD',oil:'OANDA:WTICOUSD',gold:'OANDA:XAUUSD'});
 for(const raw of [null,'null','undefined','{bad','[]','"text"'])assert.deepEqual(restoreFeedChoices(raw),{});
 assert.deepEqual(restoreFeedChoices(JSON.stringify({nasdaq:null,nq:'null',gold:'OANDA:NAS100USD',unknown:'OANDA:XAUUSD'})),{});
 assert.deepEqual(restoreFeedChoices(JSON.stringify({nasdaq:'NASDAQ:NDX'})),{nasdaq:'NASDAQ:NDX'});
});
