import type {Job} from './app';
export type ResultOrigin=Readonly<{source:string;configuration:string;revision:number;run:number}>;
export type OwnedResult<T>=Readonly<{origin:ResultOrigin;value:T}>;
export function sourceIdentity(selection:number,job:Pick<Job,'input'|'zip_member'|'input_csv'>){return JSON.stringify([selection,job.input??'',job.zip_member??null,job.input_csv]);}
export function resultOrigin(source:string,configuration:Job,revision:number,run:number):ResultOrigin {
 return Object.freeze({source,configuration:JSON.stringify(configuration),revision,run});
}
export const ownedResult=<T>(origin:ResultOrigin,value:T):OwnedResult<T>=>Object.freeze({origin,value});
export const belongsToSource=(origin:ResultOrigin|null|undefined,source:string)=>origin?.source===source;
export const belongsToDraft=(origin:ResultOrigin|null|undefined,source:string,revision:number)=>belongsToSource(origin,source)&&origin?.revision===revision;
