export const sizeUnits={B:1,KB:1000,MB:1000**2,GB:1000**3,TB:1000**4,KiB:1024,MiB:1024**2,GiB:1024**3,TiB:1024**4} as const;
export type SizeUnit=keyof typeof sizeUnits;
export type SizeControls={input:HTMLInputElement;unit:HTMLSelectElement};

export function parseAmount(text:string,unit:SizeUnit,allowZero=false):number|null{
 if(!text.trim())return null;
 const match=text.trim().match(/^\+?(\d*)(?:\.(\d*))?$/);
 if(!match||!`${match[1]}${match[2]??''}`||text.length>80||!Object.hasOwn(sizeUnits,unit))throw Error('Enter a positive amount, such as 1.5.');
 const denominator=10n**BigInt((match[2]??'').length),numerator=BigInt((match[1]||'0')+(match[2]??''))*BigInt(sizeUnits[unit]);
 if(numerator%denominator!==0n)throw Error('The amount must resolve to a whole number of bytes.');
 const bytes=numerator/denominator;
 if(bytes<0n||bytes===0n&&!allowZero||bytes>BigInt(Number.MAX_SAFE_INTEGER))throw Error('Size must be positive and within the supported range.');
 return Number(bytes);
}
export function formatAmount(bytes:number,unit:SizeUnit):string{
 if(!Number.isSafeInteger(bytes)||bytes<0)throw Error('Size must be a safe whole number of bytes.');
 const divisor=BigInt(sizeUnits[unit]),value=BigInt(bytes);let remainder=value%divisor,fraction='';
 while(remainder){remainder*=10n;fraction+=String(remainder/divisor);remainder%=divisor;}
 return String(value/divisor)+(fraction?'.'+fraction:'');
}
export function populateSize({input,unit}:SizeControls,bytes:number|null):void{
 const available=[...unit.options].map(option=>option.value as SizeUnit);
 const chosen=bytes==null?'MiB':available.filter(name=>bytes>=sizeUnits[name]&&bytes%sizeUnits[name]===0).sort((a,b)=>sizeUnits[b]-sizeUnits[a])[0]??available[0];
 unit.value=chosen;unit.dataset.currentUnit=chosen;input.value=bytes==null?'':formatAmount(bytes,chosen);
}
export function readSize({input,unit}:SizeControls):number|null{
 if(input.validity?.badInput)throw Error('Enter a positive amount, such as 1.5.');
 const bytes=parseAmount(input.value,unit.value as SizeUnit);
 if(bytes===null&&input.required)throw Error('Enter a size.');return bytes;
}
export function createSizeControl(input:HTMLInputElement,available:SizeUnit[]):SizeControls{
 const original=input.closest('label')!,field=document.createElement('div'),group=document.createElement('div'),unit=document.createElement('select'),unitLabel=document.createElement('label');
 field.className='quantity-field';group.className='quantity-input';original.before(field);field.append(original);original.htmlFor=input.id;
 const notes=[...original.querySelectorAll('small')];unit.dataset.sizeUnit='true';unit.id=input.id+'-unit';unit.name=unit.id;unit.title='Switching units preserves the size. KB/MB/GB/TB use powers of 1000; KiB/MiB/GiB/TiB use powers of 1024.';unitLabel.htmlFor=unit.id;unitLabel.className='sr-only';unitLabel.textContent=original.childNodes[0].textContent!.trim()+' unit';
 for(const name of available){const option=document.createElement('option');option.value=name;option.textContent=name==='B'?'bytes':name;unit.append(option);}
 unit.value='MiB';unit.dataset.currentUnit='MiB';input.dataset.quantity='true';if(input.id!=='memory')input.min='0';input.type='number';input.step='any';input.inputMode='decimal';input.name=input.id;
 group.append(input,unitLabel,unit);field.append(group,...notes);
 unit.addEventListener('input',()=>{
  const previous=unit.dataset.currentUnit as SizeUnit;
  if(input.validity.badInput){unit.value=previous;return;}
  try{const bytes=parseAmount(input.value,previous,true);input.value=bytes===null?'':formatAmount(bytes,unit.value as SizeUnit);unit.dataset.currentUnit=unit.value;}
  catch{unit.value=previous;}
 });
 return {input,unit};
}
