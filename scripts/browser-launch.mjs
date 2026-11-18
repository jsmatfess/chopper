// The validation harnesses always use disposable contexts/profiles. A channel
// selects an installed supported browser, never a user's existing profile.
export const browserChannel = process.env.CHOPPER_BROWSER_CHANNEL || 'bundled-chromium';
if (!['bundled-chromium', 'chrome', 'msedge'].includes(browserChannel)) {
  throw new Error('CHOPPER_BROWSER_CHANNEL must be bundled-chromium, chrome or msedge.');
}
export const browserLaunchOptions = browserChannel === 'bundled-chromium' ? {} : {channel: browserChannel};

// Protected acceptance is explicit; ordinary CI retains the options above.
import {readPacket,verifyInputs,validateGuard,startSmallObservation} from './browser-small-observer.mjs';
import {readFile,open,appendFile} from 'node:fs/promises';
const packetPath=process.env.CHOPPER_SMALL_CONTRACT_PACKET;
if(process.env.CHOPPER_SMALL_CONTRACT_REQUIRED==='1'&&!packetPath)throw new Error('Protected SMALL acceptance requires monitor configuration');
export const smallContractPacket=packetPath?await readPacket(packetPath,browserChannel):null;
let receiptInitialized=false;
export async function preflightSmallContract(){
 if(!smallContractPacket)return;
 if(process.platform!=='win32')throw new Error('Protected SMALL acceptance requires native Windows owned Job');
 if(!receiptInitialized){const file=await open(smallContractPacket.receipt,'ax');await file.close();receiptInitialized=true;}
 try{
  await verifyInputs(smallContractPacket);
  validateGuard(JSON.parse(await readFile(smallContractPacket.guard,'utf8')),smallContractPacket,{initial:true});
  await appendFile(smallContractPacket.receipt,JSON.stringify({type:'launch-preflight',sampled_ms:Date.now(),packet:smallContractPacket.packetIdentity})+'\n');
 }catch(error){await appendFile(smallContractPacket.receipt,JSON.stringify({type:'preflight-error',sampled_ms:Date.now(),error:String(error)})+'\n');throw error;}
}
export async function launchContractBrowser(chromium){
 await preflightSmallContract();
 return chromium.launch(contractBrowserLaunchOptions(smallContractPacket));
}
export async function launchContractPersistentContext(chromium,profile){
 await preflightSmallContract();
 return chromium.launchPersistentContext(profile,contractBrowserLaunchOptions(smallContractPacket));
}
export function contractBrowserLaunchOptions(packet,base=browserLaunchOptions){
 if(!packet)return base;
 // Browser.getBrowserCommandLine requires this flag; Playwright may omit it.
 const args=[...(base.args??[])];
 if(!args.includes('--enable-automation'))args.push('--enable-automation');
 return {...base,executablePath:packet.executable,args};
}
export const observeContractBrowser=(browser,context,origin,profile)=>startSmallObservation({packet:smallContractPacket,browser,context,origin,profile});
