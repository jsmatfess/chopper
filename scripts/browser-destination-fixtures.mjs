import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {disableStreamingOverlap} from './browser-async-destination.mjs';
import {build} from '../ui/node_modules/esbuild/lib/main.js';

// The staged copy remains a production path for ZIP. Exercise it with plain
// files in fault/benchmark fixtures without adding a browser-side test flag.
export async function stagedDestinationWorker(){
  const directory=fileURLToPath(new URL('../ui/src/browser/',import.meta.url));
  const source=await readFile(directory+'engine-worker.ts','utf8');
  const staged=source.replace(/directDestination=type==='run-direct'[^;]+;/,'directDestination=false;');
  if(staged===source)throw new Error('Staged destination fixture could not select the copy path');
  const result=await build({stdin:{contents:disableStreamingOverlap(staged),resolveDir:directory,sourcefile:'engine-worker.ts',loader:'ts'},bundle:true,format:'esm',minify:true,write:false});
  return result.outputFiles[0].text;
}

export function destinationFixture(rows){
  return 'id,key,payload\n'+Array.from({length:rows},(_,i)=>
    `${i},${i%8},${String(i).padStart(7,'0')}${'abcXYZ0123456789'.repeat(31)}\n`).join('');
}
