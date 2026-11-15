import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studyHourlyFvgMidpointAsOf} from '../lib/hourly-fvg-midpoint-study.ts';
import type {FvgSource} from '../lib/hourly-fvg-midpoint-study.ts';
import type {Bar} from '../lib/research.ts';

// Synthetic boundary control: a valid cutoff must proceed to archive
// validation, not be mislabeled as an invalid timestamp. No prices are used.
test('valid UTC as-of boundaries reach archive validation',()=>{
 const source={} as FvgSource;
 let archiveReads=0;
 const archive=new Proxy([] as Bar[],{
  get(_target,key){
   if(key==='length') {archiveReads++;throw Error('archive validation reached');}
   return Reflect.get(_target,key);
  },
 });
 for(const cutoff of [3600,Date.UTC(2100,0,1)/1000]){
  assert.throws(()=>studyHourlyFvgMidpointAsOf(archive,source,cutoff),
   /archive validation reached/);
 }
 assert.equal(archiveReads,2);
});
