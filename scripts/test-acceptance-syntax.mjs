import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,writeFileSync,symlinkSync,rmSync,existsSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {dirname,join,resolve} from 'node:path';
import {createRequire} from 'node:module';
import test from 'node:test';
import {checkSyntax} from './acceptance-syntax.mjs';

const require=createRequire(new URL('../ui/package.json',import.meta.url));
const compiler=resolve(require.resolve('esbuild'),'../..');
async function fixture(files,check) {
 const root=mkdtempSync(join(tmpdir(),'chopper-preflight-syntax-'));
 try {
  mkdirSync(join(root,'ui/node_modules'),{recursive:true});
  writeFileSync(join(root,'ui/package.json'),'{}');
  symlinkSync(compiler,join(root,'ui/node_modules/esbuild'),'junction');
  for(const [name,contents]of Object.entries(files)) {
   mkdirSync(dirname(join(root,name)),{recursive:true});writeFileSync(join(root,name),contents);
  }
  await check(root,join(root,'main.mjs'));
 } finally {rmSync(root,{recursive:true,force:true});}
}

test('bundles complete closure without evaluating selected code or writing output',async()=>{
 await fixture({'main.mjs':"import {value} from './helper.mjs'; throw Error('must not evaluate '+value);",
  'helper.mjs':'export const value=1;'},async(root,entry)=>{
  const result=await checkSyntax(root,[entry]);
  assert.deepEqual(Object.keys(result.metafile.inputs).sort(),['helper.mjs','main.mjs']);
  assert.deepEqual(result.runtime_pending,[]);
  assert.match(result.node,/^v\d+/);assert.match(result.esbuild,/^\d+\./);
  assert.equal(existsSync(join(root,'preflight-output')),false);
 });
});
for(const [name,files,expected]of [
 ['missing helper',{'main.mjs':"import './missing.mjs';"},/Could not resolve/],
 ['missing named export',{'main.mjs':"import {missing} from './helper.mjs'; console.log(missing);",'helper.mjs':'export const present=1;'},/No matching export/],
 ['missing named package export',{'main.mjs':"import {definitelyMissingPreflightExport} from 'esbuild'; console.log(definitelyMissingPreflightExport);"},/No matching export/],
 ['unused missing named package export',{'main.mjs':"import {definitelyMissingPreflightExport} from 'esbuild'; console.log('unused');"},/No matching export/],
 ['missing named package re-export',{'main.mjs':"import {missing} from './helper.mjs'; console.log(missing);",
  'helper.mjs':"export {definitelyMissingPreflightExport as missing} from 'esbuild';"},/No matching export/],
 ['missing named builtin export',{'main.mjs':"import {missingPreflightBuiltin} from 'node:fs'; console.log(missingPreflightBuiltin);"},/No matching export/],
 ['missing named builtin re-export',{'main.mjs':"import {missing} from './helper.mjs'; console.log(missing);",
  'helper.mjs':"export {missingPreflightBuiltin as missing} from 'fs';"},/No matching export/],
 ['syntax fault',{'main.mjs':'const = ;'},/Expected/],
 ['missing selected package',{'main.mjs':"import {chromium} from 'playwright'; console.log(chromium);"},/Cannot find module 'playwright'/],
 ['unsupported package',{'main.mjs':"import 'unknown-package';"},/Unsupported package runtime probe/],
 ['missing package runtime API',{'main.mjs':"import {chromium} from 'playwright'; console.log(chromium);",
  'ui/node_modules/playwright/package.json':'{"name":"playwright","version":"0.0.0","main":"index.mjs"}',
  'ui/node_modules/playwright/index.mjs':'export const chromium={launch(){}};'},/Missing playwright chromium runtime API/],
])test(name,async()=>fixture(files,async(root,entry)=>{
 await assert.rejects(checkSyntax(root,[entry]),expected);
 assert.equal(existsSync(join(root,'preflight-output')),false);
}));
test('nonliteral imports remain explicit runtime obligations',async()=>{
 await fixture({'main.mjs':'const target=process.argv[2]; import(target); require(target);'},async(root,entry)=>{
  const result=await checkSyntax(root,[entry]);
  assert.deepEqual(result.runtime_pending.map(item=>item.id).sort(),['unsupported-dynamic-import','unsupported-require-call']);
 });
});
test('external package runtime API is checked without bundling its internals',async()=>{
 await fixture({'main.mjs':"import {build} from 'esbuild'; console.log(build);"},async(root,entry)=>{
  const result=await checkSyntax(root,[entry]);
  assert.deepEqual(Object.keys(result.metafile.inputs),['main.mjs']);
  assert.equal(result.packages[0].name,'esbuild');
  assert.equal(result.packages[0].version,result.esbuild);
  assert.ok(result.packages[0].exports.includes('build'));
  assert.match(result.packages[0].sha256,/^[a-f0-9]{64}$/);
 });
});
test('package exports support aliases and star re-exports without evaluating selected code',async()=>{
 await fixture({'main.mjs':"import {compile,build} from './helper.mjs'; throw Error('must not evaluate '+compile+build);",
  'helper.mjs':"export {build as compile} from 'esbuild'; export * from 'esbuild';"},async(root,entry)=>{
  const result=await checkSyntax(root,[entry]);
  assert.deepEqual(Object.keys(result.metafile.inputs).sort(),['helper.mjs','main.mjs']);
  assert.equal(result.packages.length,1);
 });
});
test('builtin exports link without evaluating selected code or entering package inventory',async()=>{
 await fixture({'main.mjs':"import {readFileSync} from 'node:fs'; throw Error('must not evaluate '+readFileSync);"},async(root,entry)=>{
  const result=await checkSyntax(root,[entry]);
  assert.deepEqual(Object.keys(result.metafile.inputs),['main.mjs']);
  assert.deepEqual(result.packages,[]);
  assert.deepEqual(result.runtime_pending,[]);
 });
});
