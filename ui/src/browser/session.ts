import {sourceIdentity,resultOrigin,ownedResult,belongsToSource,belongsToDraft,type ResultOrigin,type OwnedResult} from '../result-ownership';
import {verifyPublication,type VerifiedPublication} from './publication';
import type {Job,State,Analysis,InputProfile} from '../app';
import {ExecutionHistory,type Observation} from './execution-history';

// Browser effects have a real adapter in client.ts and controlled adapters in
// lifecycle tests. No worker or ownership token escapes this module's interface.
export interface BrowserEffects {
  supported():void;
  lock(name:string,hold:()=>Promise<void>):Promise<unknown>;
  worker(path:string):Worker;
  channel():MessageChannel;
  shared(bytes:number):SharedArrayBuffer;
  uuid():string;
  timeout(callback:()=>void,ms:number):number;
  clearTimeout(id:number):void;
  diagnostic(message:unknown):void;
  historyChanged(history:ExecutionHistory|null):void;
}

class WorkerSession {
  private engine:Worker|null=null;
  private storage:Worker|null=null;
  private unlock:(()=>void)|null=null;
  private serial=0;
  private ready:Promise<Job>|null=null;
  private cleanup:Promise<void>|null=null;
  private readonly pending=new Map<number,{resolve:(value:any)=>void;reject:(error:Error)=>void}>();
  private readonly cancelled:Promise<never>;
  private cancel!:()=>void;
  retired=false;
  private profileInput:File|null=null;
  private credit:Int32Array|null=null;
  private failure:Error|null=null;
  private outputName='';
  constructor(private effects:BrowserEffects,private message:(data:any,session:WorkerSession)=>void,
    private failed:(error:Error,session:WorkerSession)=>void){
    this.cancelled=new Promise((_,reject)=>{this.cancel=()=>reject(new Error('Cancelled'));});
    // Retirement also covers a session with no caller currently awaiting startup.
    void this.cancelled.catch(()=>{});
  }
  start():Promise<Job>{return this.ready??=this.initialize();}
  private alive(){if(this.retired)throw new Error('Cancelled');if(this.failure)throw this.failure;}
  private wait<T>(promise:Promise<T>):Promise<T>{return Promise.race([promise,this.cancelled]);}
  private rejectPending(error:Error){for(const p of this.pending.values())p.reject(error);this.pending.clear();}
  private transportFailed(error:Error){
    if(this.retired||this.failure)return;
    this.failure=error;this.rejectPending(error);this.failed(error,this);
  }
  exportTo(output:FileSystemDirectoryHandle){this.outputName=output.name;}
  exportPath(folder:string){return this.outputName+'/'+folder;}
  beginObservation(){this.credit=new Int32Array(this.effects.shared(4));}
  observationRequest(run:number|undefined,enabled:boolean){
    return {observationRun:run,observationCredit:enabled?this.credit?.buffer:undefined};
  }
  acknowledgeObservation(){if(this.credit)Atomics.store(this.credit,0,0);}
  async profile(job:Job,file:File){
    const result=await this.request('profile',{job,file,resetProfile:this.profileInput!==file});
    if(!this.retired)this.profileInput=file;
    return result;
  }
  private async initialize():Promise<Job>{
    this.effects.supported();
    // Quota estimates are advisory snapshots, not a job budget. OPFS writes
    // enforce the browser’s current physical quota, including staged output.
    const available=Number.MAX_SAFE_INTEGER;
    const shared=this.effects.shared(16+1024*1024),channel=this.effects.channel(),jobId=this.effects.uuid();
    await this.wait(new Promise<void>((resolve,reject)=>{
      void this.effects.lock('chopper-'+jobId,async()=>{
        // A queued Web Lock may be granted after retirement. It must never
        // initialize workers or overwrite another session's release function.
        if(this.retired)return;
        await new Promise<void>(release=>{this.unlock=release;resolve();});
      }).catch(reject);
    }));this.alive();
    const storage=this.storage=this.effects.worker('/storage-worker.js');
    await this.wait(new Promise<void>((resolve,reject)=>{
      storage.onerror=e=>reject(new Error(e.message));
      storage.onmessage=({data})=>data.error?reject(new Error(data.error)):data.ready&&resolve();
      storage.postMessage({type:'init',jobId,available,shared,port:channel.port1},[channel.port1]);
    }));this.alive();
    storage.onerror=e=>this.transportFailed(new Error(e.message));
    storage.onmessage=({data})=>{if(data.error)this.transportFailed(new Error(data.error));};
    const engine=this.engine=this.effects.worker('/engine-worker.js');
    engine.onerror=e=>this.transportFailed(new Error(e.message));
    engine.onmessage=({data})=>{
      this.message(data,this);
      if(this.retired)return;
      const pending=this.pending.get(data.id);
      if(pending){this.pending.delete(data.id);data.error?pending.reject(new Error(data.error)):pending.resolve(data.result);}
    };
    return await this.request('init',{available,shared,port:channel.port2},[channel.port2]);
  }
  request(type:string,data:Record<string,unknown>={},transfer:Transferable[]=[]):Promise<any>{
    return new Promise((resolve,reject)=>{
      this.alive();
      const id=++this.serial;this.pending.set(id,{resolve,reject});
      try{this.engine!.postMessage({id,type,...data},transfer);}
      catch(error){
        this.pending.delete(id);reject(error);
        this.transportFailed(error instanceof Error?error:new Error(String(error)));
      }
    });
  }
  retire():Promise<void>{
    if(this.cleanup)return this.cleanup;
    this.retired=true;this.cancel();this.ready=null;this.engine?.terminate();this.engine=null;
    this.rejectPending(new Error('Cancelled'));this.profileInput=null;
    const storage=this.storage,release=this.unlock;this.storage=null;this.unlock=null;
    this.cleanup=(async()=>{
      try{if(storage)await new Promise<void>((resolve,reject)=>{
        const finish=(error?:Error)=>{this.effects.clearTimeout(timer);storage.terminate();error?reject(error):resolve();};
        const timer=this.effects.timeout(()=>finish(new Error('Temporary storage cleanup timed out. Reload and clear temporary storage.')),15000);
        storage.onerror=e=>finish(new Error(e.message));
        storage.onmessage=({data})=>{if(data.cleaned||data.error){this.message({retiredStorage:data.storage},this);finish(data.error?new Error(data.error):undefined);}};
        try{storage.postMessage({type:'cleanup'});}catch(error){finish(error instanceof Error?error:new Error(String(error)));}
      });}finally{release?.();}
    })();return this.cleanup;
  }
}

/** Owns lifecycle decisions across replaceable worker sessions. Retained history
 * is independent of the workers and is rendered only through the client adapter. */
export class BrowserLifecycle {
  readonly diagnostics:Record<string,unknown>={};
  private profiling=false;
  private input:File|null=null;
  private output:FileSystemDirectoryHandle|null=null;
  private session:WorkerSession|null=null;
  private latestSession:WorkerSession|null=null;
  private generation=0;
  private folder='';
  private prepared: {output:FileSystemDirectoryHandle;origin:ResultOrigin}|null=null;
  private inputSelection=0;
  private draftRevision=0;
  private currentSource:string|null=null;
  private observationSerial=0;
  private history:ExecutionHistory|null=null;
  private exporting=false;
  private readonly state:State={status:'idle',progress:{phase:'',rows:0,temp_bytes:0},analysis:null,error:null,output:null};
  constructor(private effects:BrowserEffects){}
  selectInput(input:File){this.input=input;this.inputSelection++;this.currentSource=null;}
  invalidateDraft(source?:string){this.draftRevision++;if(source!==undefined)this.currentSource=source;}
  selectOutput(output:FileSystemDirectoryHandle){this.output=output;}
  enableProfiling(){this.profiling=true;}
  snapshot():State{return structuredClone(this.state);}
  private setProfile(result:OwnedResult<InputProfile>){this.state.profile=result.value;this.state.origins={...this.state.origins,profile:result.origin};}
  private setAnalysis(result:OwnedResult<Analysis>){this.state.analysis=result.value;this.state.origins={...this.state.origins,analysis:result.origin};}
  private clearResults(){this.state.analysis=null;this.state.profile=null;this.state.origins={};}
  private showHistory(){try{this.effects.historyChanged(this.history);}catch{if(this.history)this.history.unavailable=true;}}
  private receive(data:any,session:WorkerSession){
    if(data.retiredStorage){if(this.profiling&&this.latestSession===session)this.diagnostics.storage=data.retiredStorage;return;}
    if(session!==this.session||session.retired){
      const observation:Observation|undefined=data.observation??data.observationFinal;
      if(this.history&&data.observationRun===this.history.run&&observation){
        try{
          const confirmed:Observation={completedStages:observation.completedStages,unavailable:observation.unavailable,events:observation.events,eventsOmitted:observation.eventsOmitted,timeline:observation.timeline?.filter(window=>window.status!=='active'),timeline_seconds:observation.timeline_seconds};
          for(const key of ['read','write','export','marker'] as const){const value=observation[key];if(value?.status==='completed')confirmed[key]=value;}
          if(observation.physical)confirmed.physical=observation.physical.filter(step=>step.status==='completed');
          this.history.accept(data.observationRun,confirmed);this.showHistory();
        }catch{this.history.unavailable=true;}
      }
      return;
    }
    if(data.observation||data.observationFinal){
      try{this.history?.accept(data.observationRun,data.observation??data.observationFinal);this.showHistory();}
      catch{if(this.history)this.history.unavailable=true;}
      finally{if(data.observation)session.acknowledgeObservation();}
    }
    if(data.profile)this.diagnostics[data.profile.phase]=data.profile.metrics;
    if(data.progress)this.state.progress=data.progress;
    if(data.exporting){this.exporting=true;this.state.output=session.exportPath(data.exporting);}
    if(data.diagnostic)this.effects.diagnostic(data.diagnostic);
  }
  private start():WorkerSession{
    if(!this.session)this.latestSession=this.session=new WorkerSession(this.effects,
      (data,session)=>this.receive(data,session),(error,session)=>this.sessionFailed(error,session));
    return this.session;
  }
  private sessionFailed(error:Error,session:WorkerSession){
    if(session!==this.session||session.retired)return;
    void this.fail(error,this.generation);
  }
  private stop():Promise<void>{
    this.history?.interrupt('unknown');this.showHistory();
    this.generation++;const session=this.session;this.session=null;this.prepared=null;
    return session?.retire()??Promise.resolve();
  }
  private async completeRun(publication:VerifiedPublication){
    this.state.output=publication.output;
    const cleanup=this.stop(),current=this.generation;
    try{await cleanup;}catch(error){if(current===this.generation)this.state.error=String(error);}
    if(current===this.generation)this.state.status='complete';
  }
  private async fail(error:unknown,current:number){
    if(current!==this.generation)return;
    this.state.status='failed';this.state.error=String(error)+(this.exporting?` Any incomplete export is in ${this.state.output}; only folders with a valid CHOPPER-COMPLETE.json record are complete.`:'');
    const cleanup=this.stop(),retirement=this.generation;
    try{await cleanup;}catch(error){if(retirement===this.generation)this.state.error+=' '+String(error);}
  }
  private async setup(promise:Promise<unknown>,current:number){
    try{await promise;}catch(error){
      if(current===this.generation){this.state.status='failed';this.state.error=String(error);await this.stop();}
      throw error;
    }
  }
  private active(){return ['profiling','analyzing','running'].includes(this.state.status);}
  private async permission(output:FileSystemDirectoryHandle){
    const handle=output as FileSystemDirectoryHandle & {requestPermission?:(options:{mode:string})=>Promise<string>};
    if(handle.requestPermission&&await handle.requestPermission({mode:'readwrite'})!=='granted')throw new Error('Output folder write permission was not granted.');
  }
  async execute(path:string,data?:any):Promise<any>{
    if(path==='state')return this.snapshot();
    if(path==='defaults'){
      const session=this.start(),current=this.generation;
      try{const defaults=await session.start();return {...defaults,input:'',output:''};}
      catch(error){if(current===this.generation)await this.stop();throw error;}
    }
    if(path==='columns'||path==='preview'||path==='sniff'){
      data=structuredClone(data);
      if(!this.input)throw new Error('Choose an input file with Browse to load its columns.');
      if(this.active())throw new Error('Wait for the active job to finish before loading columns.');
      const file=this.input,session=this.start();await this.setup(session.start(),this.generation);
      return await session.request(path,{job:data,file});
    }
    if(path==='profile'){
      data=structuredClone(data);
      if(this.active())throw new Error('A job is active.');
      if(!this.input)throw new Error('Choose an input file with Browse.');
      this.state.status='profiling';this.state.error=null;this.clearResults();this.state.output=null;this.exporting=false;
      const session=this.start(),current=this.generation,file=this.input;
      const origin=resultOrigin(sourceIdentity(this.inputSelection,data),data,this.draftRevision,current);
      await this.setup(session.start(),current);if(current!==this.generation)return {};
      void session.profile(data,file).then(result=>{
        if(current!==this.generation)return;
        if(!belongsToSource(origin,this.currentSource??sourceIdentity(this.inputSelection,data))){this.state.status='idle';this.state.profile=null;return;}
        this.setProfile(ownedResult(origin,result));this.state.status='profiled';
      }).catch(error=>this.fail(error,current));return {};
    }
    if(path==='analyze'||path==='run-direct'){
      const direct=path==='run-direct';data=structuredClone(data);
      if(this.active())throw new Error('A job is active.');
      if(!this.input||!this.output)throw new Error('Choose an input file and an output folder with Browse.');
      if(data.resources.temp_dir)throw new Error('Browser temporary storage is managed by the browser; leave temporary directory blank.');
      const file=this.input,output=this.output;
      const origin=resultOrigin(sourceIdentity(this.inputSelection,data),data,this.draftRevision,this.generation+1);
      if(direct){
        const current=this.generation;await this.permission(output);if(current!==this.generation)return {};
        if(this.active())throw new Error('A job is active.');
      }
      this.state.status=direct?'running':'analyzing';this.state.error=null;
      const cleanup=this.stop(),current=this.generation;
      await this.setup((async()=>{
        await cleanup;if(current!==this.generation)return;
        if(direct){try{this.history=new ExecutionHistory(++this.observationSerial,data);this.showHistory();}catch{this.history=null;}}
        const session=this.start();if(direct&&this.history){try{session.beginObservation();}catch{this.history=null;}}
        await session.start();
      })(),current);
      if(current!==this.generation)return {};
      this.folder='chopper-results-'+this.effects.uuid();this.exporting=false;
      this.state.status=direct?'running':'analyzing';this.state.error=null;this.clearResults();this.state.output=null;
      for(const key of Object.keys(this.diagnostics))delete this.diagnostics[key];
      const session=this.session!;session.exportTo(output);
      void session.request(direct?'run-direct':'analyze',{job:data,file,profiling:this.profiling,output,folder:this.folder,...session.observationRequest(this.history?.run,direct&&!this.history?.unavailable)}).then(async result=>{
        if(current!==this.generation)return;
        const analysis=result.analysis as Analysis;
        analysis.warnings.push('Browser export is not atomic. A valid CHOPPER-COMPLETE.json record marks successful completion.'+(direct?'':' Keep this tab open until saving finishes.'));
        this.setAnalysis(ownedResult(origin,analysis));
        if(direct){await this.completeRun(verifyPublication(result,this.folder,session.exportPath(this.folder)));}
        else{this.prepared={output,origin};this.state.status='ready';this.state.output=output.name+'/'+this.folder;}
      }).catch(error=>this.fail(error,current));return {};
    }
    if(path==='run'){
      if(this.state.status!=='ready')throw new Error('Prepare exact outputs before confirming.');
      const prepared=this.prepared;
      if(!prepared||!belongsToDraft(prepared.origin,this.currentSource??sourceIdentity(this.inputSelection,JSON.parse(prepared.origin.configuration)),this.draftRevision))throw new Error('Input or configuration changed. Prepare exact outputs again before confirming.');
      this.state.status='running';const current=this.generation,output=prepared.output,folder=this.folder;
      try{await this.permission(output);}catch(error){if(current===this.generation)this.state.status='ready';throw error;}
      if(current!==this.generation)return {};
      void this.session!.request('run',{output,folder}).then(async result=>{
        if(current!==this.generation)return;await this.completeRun(verifyPublication(result,folder,output.name+'/'+folder));
      }).catch(error=>this.fail(error,current));return {};
    }
    if(path==='cancel'){
      this.history?.interrupt('interrupted');this.showHistory();
      const wasExporting=this.exporting,cancelledOutput=this.state.output,cleanup=this.stop(),current=this.generation;
      let failure:string|null=null;try{await cleanup;}catch(error){failure=String(error);}
      if(current!==this.generation)return {};
      this.state.status='cancelled';this.clearResults();
      const warning=wasExporting?`Export cancelled. Check ${cancelledOutput}: a valid CHOPPER-COMPLETE.json record marks completed results; otherwise files are incomplete.`:null;
      this.state.error=failure!==null?[warning,`Temporary storage cleanup failed: ${failure}`].filter(Boolean).join(' '):warning;
      this.exporting=false;return {};
    }
    throw new Error('Unknown browser operation');
  }
}
