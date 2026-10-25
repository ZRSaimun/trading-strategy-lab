import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import ts from 'typescript';
import {renderToStaticMarkup} from 'react-dom/server';
import {replayEvidence} from '../lib/replay-evidence.ts';
const require=createRequire(import.meta.url);
const code=ts.transpileModule(readFileSync(new URL('../components/ReplayEvidence.tsx',import.meta.url),'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS}}).outputText;
const exports:any={};
runInNewContext(code,{exports,require:(name:string)=>name==='../lib/replay-evidence'?{replayEvidence}:require(name)});
const component=exports.default;
const bar=(time:number,observed_minutes=5)=>({time,open:10,high:12,low:9,close:11,volume:null,observed_minutes});
test('rendered panel exposes missing provenance and empty window honestly',()=>{
 const html=renderToStaticMarkup(component({bars:[],frame:'5m'}));
 assert.match(html,/NO_DATA/);assert.match(html,/Unavailable/);assert.match(html,/No execution/);
});
test('rendered prefix includes exact provenance and UTC opening bounds',()=>{
 const html=renderToStaticMarkup(component({bars:[bar(0),bar(300)],frame:'5m',source:'Exact <BID> source',sha256:'a'.repeat(64)}));
 assert.match(html,/Exact &lt;BID&gt; source/);assert.match(html,/a{64}/);
 assert.match(html,/1970-01-01T00:05:00.000Z/);assert.doesNotMatch(html,/00:10:00/);
 assert.match(html,/not authentication/);
});
test('partial coverage and gaps remain visible as insufficient evidence',()=>{
 const html=renderToStaticMarkup(component({bars:[bar(0),bar(600,2)],frame:'5m'}));
 assert.match(html,/INSUFFICIENT_DATA/);assert.match(html,/closures are not classified/);
});
test('terminal wires replay panel to chart prefix and guards it with replay mode',()=>{
 const terminal=readFileSync(new URL('../components/Terminal.tsx',import.meta.url),'utf8');
 assert.match(terminal,/replaying&&<ReplayEvidence bars=\{visibleCandles\}/);
 assert.match(terminal,/replaying\?replayPrefix\(payload.candles,cursor\):payload.candles/);
});
