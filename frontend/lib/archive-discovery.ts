/** Bounded, read-only discovery of independently sourced historical ZIP archives.
 * Supports the paginated private API and safely identifies legacy 200-row responses.
 */
export const ARCHIVE_LIST_PAGE_SIZE = 200;
export type ArchiveListing = {
 id:string; provider:string; instrument:string; format:string; state:string;
 accepted:number; rejected:number; zero_volume:number;
 utc_offset_minutes?:number; archive_sha256?:string;
};
export type ArchiveListingPage = {
 items:ArchiveListing[]; hasMore:boolean; nextOffset:number|null;
 legacyPossiblyTruncated:boolean; snapshot:string|null;
};

/** An inventory changed while paging: previous pages are no longer reliable. */
export class ArchiveInventoryChangedError extends Error {
 constructor(){super('Historical archive inventory changed; refresh the archive list from the beginning.');this.name='ArchiveInventoryChangedError'}
}

const SHA256=/^[a-f0-9]{64}$/;
const textField=(value:unknown)=>typeof value==='string'&&value.trim().length>0&&value.length<=160;
const count=(value:unknown)=>Number.isSafeInteger(value)&&Number(value)>=0;
// The API sorts by instrument, provider, then dataset ID. A page that violates
// this order is unsafe to append: an import between offset pages can otherwise
// leave a misleadingly complete but silently incomplete inventory.
const listingKey=(item:ArchiveListing)=>[item.instrument,item.provider,item.id] as const;
function compareListing(a:ArchiveListing,b:ArchiveListing):number{
 const left=listingKey(a),right=listingKey(b);
 for(let i=0;i<left.length;i++){
  if(left[i]<right[i])return -1;
  if(left[i]>right[i])return 1;
 }
 return 0;
}

/** Reject malformed identities rather than presenting different sources as equivalent. */
export function parseArchiveListing(
 payload:unknown, headers:Pick<Headers,'get'>, offset:number,
 limit=ARCHIVE_LIST_PAGE_SIZE, expectedSnapshot?:string,
):ArchiveListingPage{
 if(!Number.isSafeInteger(offset)||offset<0||offset>1_000_000||
    !Number.isInteger(limit)||limit<1||limit>ARCHIVE_LIST_PAGE_SIZE)
  throw Error('Invalid historical archive discovery window');
 if(!Array.isArray(payload)||payload.length>limit)
  throw Error('Malformed historical archive listing');
 const seen=new Set<string>();
 let previous:ArchiveListing|null=null;
 for(const item of payload){
  if(!item||typeof item!=='object'||Array.isArray(item)||
     !SHA256.test(item.id)||!textField(item.provider)||
     !textField(item.instrument)||!textField(item.format)||item.state!=='READY'||
     !count(item.accepted)||!count(item.rejected)||!count(item.zero_volume)||
     (item.utc_offset_minutes!==undefined&&
       (!Number.isInteger(item.utc_offset_minutes)||Math.abs(item.utc_offset_minutes)>1440))||
     (item.archive_sha256!==undefined&&!SHA256.test(item.archive_sha256)))
   throw Error('Invalid archive source identity or import counts');
  if(seen.has(item.id))throw Error('Repeated archive identity in discovery page');
  seen.add(item.id);
  if(previous&&compareListing(previous,item as ArchiveListing)>=0)
   throw Error('Historical archive discovery page is not in stable source order');
  previous=item as ArchiveListing;
 }
 const more=headers.get('X-History-Has-More');
 const cursor=headers.get('X-History-Next-Offset');
 const snapshot=headers.get('X-History-Snapshot');
 if(snapshot!==null&&!SHA256.test(snapshot))throw Error('Invalid historical archive inventory snapshot');
 if(expectedSnapshot!==undefined){
  if(!SHA256.test(expectedSnapshot))throw Error('Invalid expected archive inventory snapshot');
  if(snapshot!==expectedSnapshot)throw new ArchiveInventoryChangedError();
 }
 if(more===null){
  if(cursor!==null||snapshot!==null)throw Error('Historical archive metadata without pagination status');
  // Pre-pagination API always returned the first 200 READY datasets, regardless
  // of offset. Do not issue further requests against it or imply completeness.
  if(offset!==0)throw Error('Server does not support paginated archive discovery');
  return {items:payload as ArchiveListing[],hasMore:false,nextOffset:null,
          legacyPossiblyTruncated:payload.length===limit,snapshot:null};
 }
 if(more!=='true'&&more!=='false')throw Error('Invalid historical archive pagination status');
 // The paginated endpoint introduced provenance fields; missing fields are a
 // version mismatch, not permission to silently treat two sources as equal.
 for(const item of payload as ArchiveListing[]){
  if(!SHA256.test(item.archive_sha256??'')||
     !Number.isInteger(item.utc_offset_minutes)||
     Math.abs(item.utc_offset_minutes!)>840||
     item.zero_volume>item.accepted)
   throw Error('Paginated archive discovery lacks valid source provenance');
 }
 if(more==='true'){
  const next=Number(cursor);
  if(cursor===null||!/^\d+$/.test(cursor)||!Number.isSafeInteger(next)||
     next!==offset+limit||next>1_000_000||payload.length!==limit)
   throw Error('Invalid historical archive pagination cursor');
  // Older paginated servers lack a consistency token. Show the first page,
  // but do not silently traverse a changing inventory with offset paging.
  if(snapshot===null){
   if(offset!==0)throw Error('Archive pagination requires a server inventory snapshot');
   return {items:payload as ArchiveListing[],hasMore:false,nextOffset:null,
           legacyPossiblyTruncated:true,snapshot:null};
  }
  return {items:payload as ArchiveListing[],hasMore:true,nextOffset:next,
          legacyPossiblyTruncated:false,snapshot};
 }
 if(cursor!==null)throw Error('Unexpected historical archive pagination cursor');
 return {items:payload as ArchiveListing[],hasMore:false,nextOffset:null,
         legacyPossiblyTruncated:false,snapshot};
}

export function appendArchiveListing(current:ArchiveListing[],next:ArchiveListingPage):ArchiveListing[]{
 if(current.length&&next.items.length&&compareListing(current.at(-1)!,next.items[0])>=0)
  throw Error('Archive discovery pages overlap or order changed; refresh inventory');
 const ids=new Set(current.map(item=>item.id));
 for(const item of next.items){
  if(ids.has(item.id))throw Error('Archive discovery pages overlap; refresh before continuing');
  ids.add(item.id);
 }
 return [...current,...next.items];
}

export async function fetchArchiveListingPage(
 fetcher:typeof fetch, offset:number, signal?:AbortSignal, snapshot?:string,
):Promise<ArchiveListingPage>{
 if(!Number.isSafeInteger(offset)||offset<0||offset>1_000_000)
  throw Error('Invalid historical archive discovery offset');
 if(offset>0&&!snapshot)throw Error('Archive pagination requires an inventory snapshot');
 if(snapshot!==undefined&&!SHA256.test(snapshot))throw Error('Invalid archive inventory snapshot');
 const url=`/api/history/datasets?offset=${offset}&limit=${ARCHIVE_LIST_PAGE_SIZE}`+
  (snapshot?`&snapshot=${snapshot}`:'');
 const response=await fetcher(url,{credentials:'same-origin',signal});
 if(response.status===409)throw new ArchiveInventoryChangedError();
 if(!response.ok)throw Error(`Historical archive discovery unavailable (${response.status})`);
 return parseArchiveListing(await response.json(),response.headers,offset,ARCHIVE_LIST_PAGE_SIZE,snapshot);
}
