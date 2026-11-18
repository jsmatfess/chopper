import {build} from '../ui/node_modules/esbuild/lib/main.js';
import {readFile,writeFile,copyFile,mkdir,stat,unlink} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {assertProductionWasm, testAssets} from './browser-artifacts.mjs';
import {themeBootstrap,hostedCsp} from './hosted-theme.mjs';
const ui=fileURLToPath(new URL('../ui/',import.meta.url));
await mkdir(ui+'dist',{recursive:true});
// Test harnesses must never ship with the production bundle.
for(const name of testAssets)await unlink(ui+'dist/'+name).catch(e=>{if(e.code!=='ENOENT')throw e;});
await stat(ui+'dist/engine.wasm').catch(()=>{throw new Error('Build the Rust browser engine first: node scripts/build-browser.mjs');});
assertProductionWasm(await readFile(ui+'dist/engine.wasm'));
await build({entryPoints:[ui+'src/app.ts'],bundle:true,minify:true,outfile:ui+'dist/app.js'});
await build({entryPoints:[ui+'src/browser/engine-worker.ts',ui+'src/browser/storage-worker.ts'],bundle:true,minify:true,format:'esm',outdir:ui+'dist'});
let html=await readFile(ui+'index.html','utf8');
html=html.replace('<link rel="stylesheet"',`<meta name="color-scheme" content="light dark"><script>${themeBootstrap}</script><link rel="stylesheet"`);
const notices=await readFile(new URL('../docs/releases/native-usage.txt',import.meta.url),'utf8');
if(/<!--|-->|--!>/.test(notices))throw new Error('Distribution notices cannot contain HTML comment delimiters.');
html+=`\n<!-- Chopper distribution notices\n${notices}\n-->\n`;
await writeFile(ui+'dist/index.html',html);
await copyFile(ui+'style.css',ui+'dist/style.css');
await writeFile(ui+'dist/_headers',`/*
  Cross-Origin-Opener-Policy: same-origin
  Cross-Origin-Embedder-Policy: require-corp
  X-Content-Type-Options: nosniff
  Referrer-Policy: no-referrer
  Cache-Control: no-cache
  Content-Security-Policy: ${hostedCsp}
`);
console.log('Hosted app built in ui/dist');
