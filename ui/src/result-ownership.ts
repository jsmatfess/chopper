import type {InputProfile,Job,State} from './app';
export type ResultOrigin=Readonly<{source:string;configuration:string;revision:number;run:number}>;
export type OwnedResult<T>=Readonly<{origin:ResultOrigin;value:T}>;
export type RunAcknowledgement=Readonly<{dispatched:boolean}>;
type SourceConfig=Pick<Job,'input'|'zip_member'|'input_csv'|'input_dialect'>;
export function sourceIdentity(selection:number,job:SourceConfig){return JSON.stringify([selection,job.input??'',job.zip_member??null,job.input_csv,job.input_dialect??null]);}
export function resultOrigin(source:string,configuration:Job,revision:number,run:number):ResultOrigin {
 return Object.freeze({source,configuration:JSON.stringify(configuration),revision,run});
}
export const ownedResult=<T>(origin:ResultOrigin,value:T):OwnedResult<T>=>Object.freeze({origin,value});
export const belongsToSource=(origin:ResultOrigin|null|undefined,source:string)=>origin?.source===source;
export const belongsToDraft=(origin:ResultOrigin|null|undefined,source:string,revision:number)=>belongsToSource(origin,source)&&origin?.revision===revision;

type PollTicket=Readonly<{sequence:number;epoch:number}>;

export class HostedResultOwnership {
  private selection=0;
  private revision=0;
  private acknowledgedRevision=-1;
  private resultSerial=0;
  private profileOrigin?:ResultOrigin;
  private analysisOrigin?:ResultOrigin;
  private profile:InputProfile|null=null;
  private commandEpoch=0;
  private activeCommands=0;
  private pollSequence=0;
  private appliedPoll=0;

  get dirty(){return this.revision!==this.acknowledgedRevision;}
  get commandPending(){return this.activeCommands>0;}

  selectInput(){this.selection++;}
  sourceKey(job:SourceConfig){return sourceIdentity(this.selection,job);}

  editDraft(source:string){
    this.revision++;
    const profileCurrent=belongsToSource(this.profileOrigin,source);
    if(!profileCurrent)this.profile=null;
    return {profileCurrent,profile:this.profile};
  }

  profileMatchesJob(job:Job){
    return this.profileOrigin?.configuration===JSON.stringify(job);
  }

  analyze(job:Job,source:string,submit:()=>Promise<unknown>){
    if(!this.profile||!belongsToSource(this.profileOrigin,source)){
      this.profileOrigin=resultOrigin(source,job,this.revision,++this.resultSerial);
    }
    return this.command(submit);
  }

  run(job:Job,source:string,submit:()=>Promise<RunAcknowledgement>){
    const revision=this.revision;
    const origin=resultOrigin(source,job,revision,++this.resultSerial);
    return this.command(async()=>{
      const {dispatched}=await submit();
      if(!dispatched)return false;
      this.analysisOrigin=origin;
      if(revision===this.revision)this.acknowledgedRevision=revision;
      return true;
    });
  }

  cancel(submit:()=>Promise<unknown>){
    return this.command(submit);
  }

  private async command<T>(submit:()=>Promise<T>){
    this.commandEpoch++;
    this.activeCommands++;
    try{return await submit();}
    finally{
      this.activeCommands--;
      this.commandEpoch++;
    }
  }

  beginPoll():PollTicket|null{
    if(this.commandPending)return null;
    return {sequence:++this.pollSequence,epoch:this.commandEpoch};
  }

  acceptPoll(ticket:PollTicket,state:Pick<State,'origins'|'profile'>,source:string){
    if(ticket.sequence<=this.appliedPoll||ticket.epoch!==this.commandEpoch||this.commandPending)return null;
    this.appliedPoll=ticket.sequence;
    this.profileOrigin=state.origins?.profile??this.profileOrigin;
    this.analysisOrigin=state.origins?.analysis??this.analysisOrigin;
    const profileCurrent=belongsToSource(this.profileOrigin,source);
    const profile=profileCurrent?state.profile??null:null;
    if(profile)this.profile=profile;
    const analysisSource=(!this.profile||!profileCurrent)&&belongsToSource(this.analysisOrigin,source)?source:null;
    return {profile,analysisSource};
  }
}
