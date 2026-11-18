import {formatAmount,populateSize,readSize,type SizeControls} from './size-units';
export type RequestedMemory = number | 'auto';
type MemoryControls = {mode:Pick<HTMLSelectElement,'value'>;manual:HTMLInputElement;unit:HTMLSelectElement};
const size=({manual,unit}:MemoryControls):SizeControls=>({input:manual,unit});
export function populateMemory(controls:MemoryControls,requested:RequestedMemory=256):void{
 controls.mode.value=requested==='auto'?'auto':'manual';populateSize(size(controls),(requested==='auto'?256:requested)*1024**2);updateMemory(controls);
}
export function updateMemory({mode,manual,unit}:MemoryControls):void{
 manual.dataset.minimumMiB??=manual.min||'32';manual.dataset.maximumMiB??=manual.max||'1048576';
 manual.min=formatAmount(Number(manual.dataset.minimumMiB)*1024**2,unit.value as 'MiB'|'GiB');manual.max=formatAmount(Number(manual.dataset.maximumMiB)*1024**2,unit.value as 'MiB'|'GiB');
 manual.step=formatAmount(1024**2,unit.value as 'MiB'|'GiB');
 manual.disabled=unit.disabled=mode.value==='auto';
}
export function readMemory(controls:MemoryControls):RequestedMemory{
 if(controls.mode.value==='auto')return 'auto';
 const bytes=readSize(size(controls));if(bytes===null||bytes%(1024**2)!==0)throw Error('Working memory must resolve to a whole number of MiB.');
 const memory=bytes/1024**2,min=Number(controls.manual.dataset.minimumMiB||32),max=Number(controls.manual.dataset.maximumMiB||1048576);
 if(memory<min||memory>max)throw Error(`Working memory must be between ${controls.manual.min} and ${controls.manual.max} ${controls.unit.value}.`);
 return memory;
}
