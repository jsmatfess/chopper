import {build} from '../ui/node_modules/esbuild/lib/main.js';
import {writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
if (process.argv.slice(2).some(arg => arg.includes('experimental-input-snapshots'))) {
  throw new Error('Direct compact/IPC input snapshots were removed; use direct CSV input. experimental-input-snapshots is unsupported.');
}
if(process.argv.slice(2).some(arg=>arg.includes('experimental-parallel-groups')||arg==='--parallel-groups')){
  throw new Error('Independent-parent batching/replay was removed; experimental-parallel-groups is unsupported.');
}
const ui=fileURLToPath(new URL('../ui/',import.meta.url));
if(process.argv.includes('--resource-contracts')){
  await build({entryPoints:[ui+'tests/resource-contract-tests.ts',ui+'tests/resource-contract-worker.ts'],bundle:true,format:'esm',outdir:ui+'dist'});
  await writeFile(ui+'dist/resource-contract-tests.html','<!doctype html><title>Chopper resource contracts</title><body>Running resource contracts…<script type="module" src="/resource-contract-tests.js"></script>');
}else{
  await build({entryPoints:[ui+'tests/browser.ts'],bundle:true,format:'esm',outfile:ui+'dist/browser-tests.js'});
  await writeFile(ui+'dist/tests.html','<!doctype html><title>Chopper browser engine tests</title><body>Running browser contracts…<script type="module" src="/browser-tests.js"></script>');
}
