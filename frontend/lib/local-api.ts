import {aggregate,parseCSV,type Bar} from './research';
type Entry={key:string;value:unknown};
async function database():Promise<IDBDatabase>{return new Promise((resolve,reject)=>{const r=indexedDB.open('trading-strategy-lab-browser-v1',1);r.onupgradeneeded=()=>r.result.createObjectStore('records',{keyPath:'key'});r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(Error('Browser storage unavailable'))})}
async function read(key:string):Promise<unknown>{const db=await database();try{return await new Promise((resolve,reject)=>{const r=db.transaction('records').objectStore('records').get(key);r.onsuccess=()=>resolve((r.result as Entry|undefined)?.value);r.onerror=()=>reject(r.error)})}finally{db.close()}}
async function write(key:string,value:unknown){const db=await database();try{await new Promise<void>((resolve,reject)=>{const tx=db.transaction('records','readwrite');tx.objectStore('records').put({key,value});tx.oncomplete=()=>resolve();tx.onerror=()=>reject(Error('Browser storage is full or unavailable; export your research'))})}finally{db.close()}}
async function log(action:string,detail:unknown){const logs=(await read('audit')||[]) as unknown[];logs.unshift({id:crypto.randomUUID(),time:Math.floor(Date.now()/1000),actor:'browser-local',action,detail});await write('audit',logs.slice(0,200))}
type Dataset={rows:Bar[];meta:{source:string;rows:number;start:number;end:number;gaps:number;retrieved_at:number;sha256:string;volume_type:string}};
type Drawing={id:string;version:number;[key:string]:unknown};
const valid=(i:string)=>{if(!['XAUUSD-IMPORT','NDX-IMPORT'].includes(i))throw Error('Unknown instrument; no substitution')};
export async function localAPI(path:string,init?:RequestInit):Promise<any>{
 const url=new URL(path,'https://local.invalid');const method=init?.method||'GET';
 const body=()=>JSON.parse(String(init?.body||'{}'));
 if(url.pathname==='/me')return {user:'browser-local'};
 if(url.pathname==='/logout')throw Error('Browser mode has no server session. Close this tab; use a device lock for privacy.');
 if(url.pathname==='/watchlist'){if(method==='PUT'){const b=body();b.instruments.forEach(valid);await write('watchlist',b.instruments);await log('watchlist.update',b);return b.instruments}return await read('watchlist')||['XAUUSD-IMPORT','NDX-IMPORT']}
 if(url.pathname==='/audit')return await read('audit')||[];
 if(url.pathname==='/import'){
  const data=init?.body as FormData;const i=String(data.get('instrument'));valid(i);
  if(data.get('rights_confirmed')!=='true')throw Error('Dataset authorization required');
  const file=data.get('file') as File;if(!file||file.size>12000000)throw Error('CSV exceeds 12 MB');
  const source=String(data.get('source')||'').trim();if(!source||source.length>160)throw Error('Source description required (maximum 160 characters)');
  const rows=parseCSV(await file.text());const volume_type=String(data.get('volume_type'));
  if(!['none','tick','exchange'].includes(volume_type))throw Error('Invalid volume classification');
  if(volume_type==='none'&&rows.some(r=>r.volume!==null))throw Error('Declare tick or exchange volume');
  const hash=await crypto.subtle.digest('SHA-256',await file.arrayBuffer());
  const meta={source,rows:rows.length,start:rows[0].time,end:rows.at(-1)!.time,gaps:rows.slice(1).filter((r,n)=>r.time-rows[n].time>60).length,retrieved_at:Math.floor(Date.now()/1000),volume_type,sha256:Array.from(new Uint8Array(hash),b=>b.toString(16).padStart(2,'0')).join('')};
  await write('dataset:'+i,{rows,meta});await log('data.import',{instrument:i,...meta});return meta;
 }
 const parts=url.pathname.split('/').filter(Boolean),i=parts[1];valid(i);
 if(parts[0]==='candles'){
  const dataset=await read('dataset:'+i) as Dataset|undefined;
  if(!dataset)return {candles:[],dataset:null,quality:{state:'NO DATA'}};
  const bars=aggregate(dataset.rows,url.searchParams.get('timeframe')||'5m');
  return {candles:bars,dataset:dataset.meta,quality:{state:'WAIT',live:false,message:'Historical browser-local data. No live feed or confirmed demo signals. Gap intervals may include market closures.'}};
 }
 if(parts[0]==='drawings'){
  const key='drawings:'+i;const drawings=(await read(key)||[]) as Drawing[];
  if(method==='GET')return drawings;
  if(method==='PUT'){const b=body();const prior=drawings.find(d=>d.id===b.id);if(b.version!==(prior?.version||0))throw Error('Drawing version conflict; reload');const doc={...b,version:b.version+1,owner:'browser-local',provenance:'manual',updated_at:Math.floor(Date.now()/1000)};await write(key,[...drawings.filter(d=>d.id!==doc.id),doc]);await log('drawing.save',{instrument:i,before:prior,after:doc});return doc}
  if(method==='DELETE'){const prior=drawings.find(d=>d.id===parts[2]);if(!prior)throw Error('Drawing not found');if(prior.version!==Number(url.searchParams.get('version')))throw Error('Drawing version conflict; reload');await write(key,drawings.filter(d=>d.id!==parts[2]));await log('drawing.delete',{instrument:i,before:prior});return {deleted:true}}
 }
 throw Error('Unavailable in browser-local mode');
}
