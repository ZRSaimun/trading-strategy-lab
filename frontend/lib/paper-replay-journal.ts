/** Restart-verifiable paper execution event log. No broker, network or durable store is bundled.
 * The caller MUST provide an atomic compare-and-swap persistent adapter for restart safety.
 */
import {PaperExecutionLedger,type PaperIdentity,type PaperRequest,type PaperQuote,type PaperOrder,type PaperEvent} from './paper-execution.ts';

export type PaperAction =
  | Readonly<{kind:'SUBMIT';request:PaperRequest}>
  | Readonly<{kind:'CANCEL';orderId:string;at:number}>
  | Readonly<{kind:'QUOTE';quote:PaperQuote}>;
export type PaperCheckpoint = Readonly<{
  version:1;identity:PaperIdentity;actions:readonly PaperAction[];
  orders:readonly PaperOrder[];events:readonly PaperEvent[];
}>;
export type StoredPaperCheckpoint = Readonly<{revision:number;json:string}>;
/** compareAndSwap MUST be atomic and persistent, never a read-then-write implementation. */
export interface PaperCheckpointStore {
  load():Promise<StoredPaperCheckpoint|null>;
  compareAndSwap(expectedRevision:number|null,next:StoredPaperCheckpoint):Promise<boolean>;
}
const MAX_BYTES=8_000_000, MAX_ACTIONS=50_000;
const keys=(value:unknown,expected:readonly string[]):boolean=>
  value!==null && typeof value==='object' && !Array.isArray(value) &&
  Object.keys(value).sort().join('|')===[...expected].sort().join('|');
const identityKeys=['instrument','provider','venue','priceSide','pointValue'];
const requestKeys=['clientOrderId','instrument','side','units','submittedAt','expiresAt','stop','target',
  'maxSpread','maxQuoteAgeSeconds','maxStopRiskCurrency','adverseSlippagePerSide','commissionPerUnitSide'];
const quoteKeys=['instrument','provider','venue','observedAt','receivedAt','bid','ask'];
const canon=(value:unknown):string=>JSON.stringify(value,(_k,v)=>
  v && typeof v==='object' && !Array.isArray(v) ? Object.fromEntries(Object.entries(v).sort(([a],[b])=>a.localeCompare(b))) : v);
const same=(a:unknown,b:unknown)=>canon(a)===canon(b);
const clone=<T>(value:T):T=>JSON.parse(JSON.stringify(value)) as T;

/** An isolated ledger with an append-only log of ALL accepted quote events, even no-fill quotes. */
export class PaperReplayJournal {
  private readonly engine:PaperExecutionLedger;
  private readonly actions:PaperAction[]=[];
  private readonly ids:string[]=[];
  readonly identity:PaperIdentity;
  constructor(identity:PaperIdentity){
    this.identity=clone(identity);
    if (!keys(identity,identityKeys)) throw Error('Invalid paper journal source identity');
    this.engine=new PaperExecutionLedger(identity);
  }
  submit(request:PaperRequest):PaperOrder {
    if (!keys(request,requestKeys)) throw Error('Invalid paper journal request fields');
    const existing=this.engine.get(request.clientOrderId);
    const order=this.engine.submit(request);
    if (!existing){
      this.actions.push({kind:'SUBMIT',request:clone(request)});
      this.ids.push(request.clientOrderId);
    }
    return order;
  }
  cancel(orderId:string,at:number):PaperOrder {
    const order=this.engine.cancel(orderId,at);
    this.actions.push({kind:'CANCEL',orderId,at});
    return order;
  }
  onQuote(quote:PaperQuote):readonly PaperEvent[] {
    if (!keys(quote,quoteKeys)) throw Error('Invalid paper journal quote fields');
    const events=this.engine.onQuote(quote);
    this.actions.push({kind:'QUOTE',quote:clone(quote)});
    return events;
  }
  get(id:string):PaperOrder|undefined{return this.engine.get(id);}
  history():readonly PaperEvent[]{return this.engine.history();}
  checkpoint():PaperCheckpoint {
    return clone({version:1,identity:this.identity,actions:this.actions,
      orders:this.ids.map(id=>this.engine.get(id)!),events:this.engine.history()});
  }
  serialize():string {
    if(this.actions.length>MAX_ACTIONS)throw Error('Paper journal exceeds action limit');
    const json=JSON.stringify(this.checkpoint());
    if(json.length>MAX_BYTES)throw Error('Paper journal exceeds size limit');
    return json;
  }
  /** Fail closed on missing/altered actions, fields, settlement or event history. */
  static restore(json:string):PaperReplayJournal {
    if(typeof json!=='string'||json.length>MAX_BYTES)throw Error('Invalid paper journal size');
    let value:unknown;
    try{value=JSON.parse(json);}catch{throw Error('Invalid paper journal JSON');}
    if(!keys(value,['version','identity','actions','orders','events']))throw Error('Invalid paper journal checkpoint fields');
    const c=value as unknown as PaperCheckpoint;
    if(c.version!==1||!keys(c.identity,identityKeys)||!Array.isArray(c.actions)||
       c.actions.length>MAX_ACTIONS||!Array.isArray(c.orders)||!Array.isArray(c.events))
      throw Error('Invalid paper journal checkpoint version or contents');
    const restored=new PaperReplayJournal(c.identity);
    try{
      for(const action of c.actions){
        if(!action || typeof action!=='object')throw Error('Invalid action');
        if(action.kind==='SUBMIT' && keys(action,['kind','request']) && keys(action.request,requestKeys))restored.submit(action.request);
        else if(action.kind==='CANCEL' && keys(action,['kind','orderId','at']))restored.cancel(action.orderId,action.at);
        else if(action.kind==='QUOTE' && keys(action,['kind','quote']) && keys(action.quote,quoteKeys))restored.onQuote(action.quote);
        else throw Error('Unknown action or extra fields');
      }
    }catch(e){throw Error('Paper journal replay failed: '+(e instanceof Error?e.message:String(e)));}
    if(!same(restored.checkpoint(),c))throw Error('Paper journal checkpoint does not match deterministic replay');
    return restored;
  }
}

/** Transactional persistent session. On a rejected save, no in-memory order/clock changes occur.
 * Multiple writers must use the store's atomic CAS; conflicts require explicit reload.
 */
export class PersistentPaperSession {
  private journal:PaperReplayJournal;
  private readonly store:PaperCheckpointStore;
  private revision:number|null;
  private constructor(journal:PaperReplayJournal,store:PaperCheckpointStore,revision:number|null){
    this.journal=journal;this.store=store;this.revision=revision;
  }
  static async open(identity:PaperIdentity,store:PaperCheckpointStore):Promise<PersistentPaperSession>{
    const saved=await store.load();
    if(saved===null)return new PersistentPaperSession(new PaperReplayJournal(identity),store,null);
    if(!Number.isSafeInteger(saved.revision)||saved.revision<0)throw Error('Invalid stored paper revision');
    const journal=PaperReplayJournal.restore(saved.json);
    if(!same(journal.identity,identity))throw Error('Stored paper source identity mismatch');
    return new PersistentPaperSession(journal,store,saved.revision);
  }
  get(id:string):PaperOrder|undefined{return this.journal.get(id);}
  checkpoint():PaperCheckpoint{return this.journal.checkpoint();}
  /** Save before publishing the state change. Never replay an order after a failed CAS. */
  async apply(action:PaperAction):Promise<PaperOrder|readonly PaperEvent[]>{
    const next=PaperReplayJournal.restore(this.journal.serialize());
    let result:PaperOrder|readonly PaperEvent[];
    if(action.kind==='SUBMIT')result=next.submit(action.request);
    else if(action.kind==='CANCEL')result=next.cancel(action.orderId,action.at);
    else if(action.kind==='QUOTE')result=next.onQuote(action.quote);
    else throw Error('Unknown paper action');
    const revision=(this.revision??-1)+1;
    const ok=await this.store.compareAndSwap(this.revision,{revision,json:next.serialize()});
    if(!ok)throw Error('Concurrent paper journal update: reload required');
    this.journal=next;this.revision=revision;
    return result;
  }
}
