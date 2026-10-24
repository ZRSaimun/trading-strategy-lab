import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ARCHIVE_LIST_PAGE_SIZE,appendArchiveListing,fetchArchiveListingPage,parseArchiveListing} from '../lib/archive-discovery.ts';
const item=(n:number)=>({id:n.toString(16).padStart(64,'0'),provider:'HistData',instrument:'XAUUSD-OTC',format:'ascii',state:'READY',accepted:1000,rejected:0,zero_volume:0,utc_offset_minutes:-300,archive_sha256:'f'.repeat(64)});
const headers=(more?:string,next?:string)=>new Headers({...(more===undefined?{}:{'X-History-Has-More':more}),...(next===undefined?{}:{'X-History-Next-Offset':next})});

test('legacy first page is accepted but 200 rows are explicitly possibly truncated',()=>{
 assert.deepEqual(parseArchiveListing([item(1)],headers(),0),{items:[item(1)],hasMore:false,nextOffset:null,legacyPossiblyTruncated:false});
 const legacy=parseArchiveListing(Array.from({length:200},(_,i)=>item(i)),headers(),0);
 assert.equal(legacy.legacyPossiblyTruncated,true);
 assert.equal(legacy.hasMore,false);
 assert.throws(()=>parseArchiveListing([item(1)],headers(),200),/does not support/);
});
test('paginated discovery returns verified next cursor and terminal page',()=>{
 const first=parseArchiveListing(Array.from({length:200},(_,i)=>item(i)),headers('true','200'),0);
 assert.equal(first.nextOffset,200);
 assert.equal(first.hasMore,true);
 const last=parseArchiveListing([item(200)],headers('false'),200);
 const all=appendArchiveListing(first.items,last);
 assert.equal(all.length,201);
 assert.equal(all[200].id,item(200).id);
 assert.equal(last.nextOffset,null);
});
test('rejects repeated identities, cross-page collisions and invalid provenance',()=>{
 assert.throws(()=>parseArchiveListing([item(1),item(1)],headers('false'),0),/Repeated/);
 assert.throws(()=>appendArchiveListing([item(1)],{items:[item(1)],hasMore:false,nextOffset:null,legacyPossiblyTruncated:false}),/overlap/);
 for(const changed of [
  {...item(1),id:'not-sha'}, {...item(1),archive_sha256:'x'},
  {...item(1),utc_offset_minutes:3000},{...item(1),accepted:-1},
  {...item(1),state:'IMPORTING'}, {...item(1),instrument:''},
 ])assert.throws(()=>parseArchiveListing([changed],headers('false'),0),/identity/);
});
test('rejects broken status and cursors rather than silently looping',()=>{
 const full=Array.from({length:ARCHIVE_LIST_PAGE_SIZE},(_,i)=>item(i));
 for(const [more,cursor] of [['true',undefined],['true','199'],['true','oops'],['false','200'],['maybe',undefined]]){
  assert.throws(()=>parseArchiveListing(full,headers(more,cursor),0),/pagination/);
 }
 assert.throws(()=>parseArchiveListing([item(1)],headers('true','200'),0),/pagination/);
 assert.throws(()=>parseArchiveListing([item(1)],headers(undefined,'200'),0),/cursor/);
 assert.throws(()=>parseArchiveListing(full,headers('true','1000200'),1000000),/pagination/);
});
test('fetcher requests only authenticated same-origin paginated listing and handles failures',async()=>{
 let called='';
 const fetcher=(async(url:string,options:RequestInit)=>{
  called=url;
  assert.equal(options.credentials,'same-origin');
  return new Response(JSON.stringify([item(1)]),{status:200,headers:headers('false')});
 }) as typeof fetch;
 const p=await fetchArchiveListingPage(fetcher,0);
 assert.equal(called,'/api/history/datasets?offset=0&limit=200');
 assert.equal(p.items.length,1);
 await assert.rejects(()=>fetchArchiveListingPage((async()=>new Response('No',{status:401})) as typeof fetch,0),/401/);
 await assert.rejects(()=>fetchArchiveListingPage(fetcher,-1),/offset/);
});


test('rejects out-of-order listings and cross-page offset drift even without duplicate IDs',()=>{
 const valid=Array.from({length:200},(_,i)=>item(i));
 assert.throws(()=>parseArchiveListing([item(2),item(1)],headers('false'),0),/source order/);
 const first=parseArchiveListing(valid,headers('true','200'),0);
 // A concurrent new READY dataset inserted ahead of the cursor may shift the
 // second page. Even if IDs do not overlap, an out-of-order page must fail.
 const shifted=parseArchiveListing([item(150),item(201)],headers('false'),200);
 assert.throws(()=>appendArchiveListing(first.items,shifted),/order changed/);
 assert.deepEqual(appendArchiveListing(first.items,parseArchiveListing([item(200)],headers('false'),200)).at(-1),item(200));
});

test('modern paginated discovery requires hash, declared fixed offset and consistent counters',()=>{
 for(const bad of [
  {...item(1),archive_sha256:undefined},
  {...item(1),utc_offset_minutes:undefined},
  {...item(1),utc_offset_minutes:900},
  {...item(1),zero_volume:1001},
 ])assert.throws(()=>parseArchiveListing([bad],headers('false'),0),/provenance|identity/);
 // Legacy non-paginated servers may not have introduced the provenance fields.
 assert.equal(parseArchiveListing([{...item(1),archive_sha256:undefined,utc_offset_minutes:undefined}],headers(),0).items.length,1);
});
