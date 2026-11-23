import {build} from '../ui/node_modules/esbuild/lib/main.js';
import {readFile,writeFile,copyFile,mkdir,stat,unlink} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {assertProductionWasm, testAssets} from './browser-artifacts.mjs';
import {themeBootstrap,hostedCsp} from './hosted-theme.mjs';
const ui=fileURLToPath(new URL('../ui/',import.meta.url));
const docsOrigin=process.env.CHOPPER_DOCS_ORIGIN;
let releaseDocs;
if(docsOrigin!==undefined){
  const {version}=JSON.parse(await readFile(ui+'package.json','utf8'));
  const url=new URL(docsOrigin);
  if(!/^https:\/\/[a-z0-9.-]+(?::\d+)?\/?$/i.test(docsOrigin)||!/^\d+\.\d+\.\d+$/.test(version)){
    throw new Error('CHOPPER_DOCS_ORIGIN requires a bare HTTPS origin and a stable app version.');
  }
  releaseDocs=new URL(`/versions/${version}/`,url).href;
}
await mkdir(ui+'dist',{recursive:true});
// Test harnesses must never ship with the production bundle.
for(const name of testAssets)await unlink(ui+'dist/'+name).catch(e=>{if(e.code!=='ENOENT')throw e;});
await stat(ui+'dist/engine.wasm').catch(()=>{throw new Error('Build the Rust browser engine first: node scripts/build-browser.mjs');});
assertProductionWasm(await readFile(ui+'dist/engine.wasm'));
await build({entryPoints:[ui+'src/app.ts'],bundle:true,minify:true,outfile:ui+'dist/app.js'});
await build({entryPoints:[ui+'src/browser/engine-worker.ts',ui+'src/browser/storage-worker.ts'],bundle:true,minify:true,format:'esm',outdir:ui+'dist'});
let html=await readFile(ui+'index.html','utf8');
const sampleMarker='id="try-sample"';
if(!html.includes(sampleMarker))throw new Error('Missing hosted sample button in index.html.');
const sample=await readFile(new URL('../examples/customers.csv',import.meta.url));
const {limits}=JSON.parse(await readFile(new URL('../examples/quickstart-job.json',import.meta.url),'utf8'));
if(!sample.length||!Number.isSafeInteger(limits.rows)||limits.rows<1)throw new Error('Invalid hosted sample CSV or row cap.');
html=html.replace(sampleMarker,`${sampleMarker} data-csv="${sample.toString('base64')}" data-rows="${limits.rows}"`);
if(releaseDocs){
  const links=[
    ['data-docs-link',releaseDocs],
    ['data-folder-docs-link',new URL('browser#choosing-an-output-folder',releaseDocs).href],
  ];
  for(const [attribute,href] of links){
    const marker=new RegExp(`${attribute} href="[^"]+"`);
    if(!marker.test(html))throw new Error(`Missing hosted link with ${attribute} in index.html.`);
    html=html.replace(marker,`${attribute} href="${href}"`);
  }
}
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
