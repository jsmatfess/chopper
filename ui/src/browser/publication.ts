export type PublicationReceipt={kind:'browser-completion-marker';version:1;folder:string;files:number;marker:'CHOPPER-COMPLETE.json'};
declare const verified:unique symbol;
export type VerifiedPublication=Readonly<{output:string;receipt:PublicationReceipt;[verified]:true}>;
// The worker creates this wire receipt only after exact marker readback. The
// session checks the destination binding before promoting a cloned response.
export function verifyPublication(result:unknown,folder:string,output:string):VerifiedPublication {
 const value=result as {output?:unknown;publication?:Partial<PublicationReceipt>};const receipt=value?.publication;
 if(value?.output!==output||!receipt||receipt.kind!=='browser-completion-marker'||receipt.version!==1||receipt.folder!==folder||receipt.marker!=='CHOPPER-COMPLETE.json'||!Number.isSafeInteger(receipt.files)||receipt.files!<1)throw new Error('Missing or invalid verified publication receipt');
 return Object.freeze({output,receipt:Object.freeze({kind:'browser-completion-marker',version:1,folder,files:receipt.files!,marker:'CHOPPER-COMPLETE.json'})}) as VerifiedPublication;
}
