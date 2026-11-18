// Isolated fake-Cargo controls; no compiler, WASM execution or browser is needed.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,writeFileSync,copyFileSync,readFileSync,existsSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';

function fixture(){
 const root=mkdtempSync(join(tmpdir(),'chopper-browser-build-'));
 for(const dir of ['scripts','sdk/bin','target/wasm32-wasip1/release','ui/dist'])mkdirSync(join(root,dir),{recursive:true});
 for(const name of ['build-browser.mjs','build-browser.sh','browser-artifacts.mjs'])copyFileSync(new URL(name,import.meta.url),join(root,'scripts',name));
 const suffix=process.platform==='win32'?'.exe':'';
 for(const name of ['clang','llvm-ar'])writeFileSync(join(root,'sdk/bin',name+suffix),'placeholder');
 writeFileSync(join(root,'target/wasm32-wasip1/release/chopper_browser.wasm'),'OLD ENGINE');
 writeFileSync(join(root,'ui/dist/engine.wasm'),'PUBLISHED BEFORE ATTEMPT');
 const hook=join(root,'fake-cargo.mjs');
 writeFileSync(hook,`import cp from 'node:child_process';
import {syncBuiltinESMExports} from 'node:module';
import {mkdirSync,writeFileSync,readFileSync,existsSync} from 'node:fs';
import {resolve,join} from 'node:path';
cp.spawnSync=(command,args,options)=>{
 if(command!=='cargo')throw new Error('unexpected subprocess');
 writeFileSync(join(options.cwd,'cargo-call.json'),JSON.stringify({args,target:options.env.CARGO_TARGET_DIR,configuredTarget:options.env.CARGO_BUILD_TARGET_DIR}));
 const config=join(options.cwd,'.cargo/config.toml');
 const configured=existsSync(config)?readFileSync(config,'utf8').match(/target-dir\\s*=\\s*"([^"]+)"/)?.[1]:undefined;
 let target=resolve(options.cwd,options.env.CARGO_TARGET_DIR||options.env.CARGO_BUILD_TARGET_DIR||configured||'target');
 const at=args.indexOf('--target-dir');if(at>=0)target=resolve(options.cwd,args[at+1]);
 const equals=args.find(a=>a.startsWith('--target-dir='));if(equals)target=resolve(options.cwd,equals.slice(13));
 if(process.env.FAKE_CARGO_FAIL)return {status:7};
 mkdirSync(join(target,'wasm32-wasip1/release'),{recursive:true});
 writeFileSync(join(target,'wasm32-wasip1/release/chopper_browser.wasm'),'NEW ENGINE');
 return {status:0};
};syncBuiltinESMExports();`);
 const run=(args=[],shell=false,extra={})=>{
  const env={...process.env,WASI_SDK_PATH:join(root,'sdk'),CARGO_TARGET_DIR:'target',...extra};
  // Node's preload replaces only Cargo dispatch inside this isolated child.
  const preload=`--import=${pathToFileURL(hook).href}`;
  env.NODE_OPTIONS=preload;
  return spawnSync(shell?'bash':process.execPath,[join(root,'scripts',shell?'build-browser.sh':'build-browser.mjs'),...args],{cwd:root,env,encoding:'utf8',timeout:10000});
 };
 return {root,run,close:()=>rmSync(root,{recursive:true,force:true})};
}

const forbidden=[['--target-dir','alternate-target'],['--target-dir=alternate-target'],
 ['--profile','dev'],['--profile=release'],['--target','other'],['--manifest-path','other/Cargo.toml'],
 ['--config','build.target-dir="alternate-target"'],['--package','other'],['--workspace'],['--artifact-dir','other']];
for(const args of forbidden)test(`artifact overrides reject before Cargo or publication: ${args.join(' ')}`,()=>{
 const f=fixture();try{
  const r=f.run(args);assert.notEqual(r.status,0,r.stdout+r.stderr);
  assert.match(r.stderr,/unsupported browser build argument/i);
  assert.equal(existsSync(join(f.root,'cargo-call.json')),false);
  assert.equal(readFileSync(join(f.root,'ui/dist/engine.wasm'),'utf8'),'PUBLISHED BEFORE ATTEMPT');
 }finally{f.close();}
});

test('default build and environment target directory copy the selected fresh engine',()=>{
 for(const target of ['target','alternate-target']){
  const f=fixture();try{
   const r=f.run(['--offline'],false,{CARGO_TARGET_DIR:target});assert.equal(r.status,0,r.stdout+r.stderr);
   assert.equal(readFileSync(join(f.root,'ui/dist/engine.wasm'),'utf8'),'NEW ENGINE');
   assert.equal(readFileSync(join(f.root,target,'wasm32-wasip1/release/chopper_browser.wasm'),'utf8'),'NEW ENGINE');
   const call=JSON.parse(readFileSync(join(f.root,'cargo-call.json'),'utf8'));
   assert.deepEqual(call.args,['build','--release','--locked','-p','chopper-browser','--target','wasm32-wasip1','--offline']);
  }finally{f.close();}
 }
});

test('feature/resource selection retains distinct asset routing',()=>{
 const f=fixture();try{
  const r=f.run(['--resource-contracts','--features','chopper/experimental-shuffle-partition','--no-default-features']);
  assert.equal(r.status,0,r.stdout+r.stderr);
  assert.equal(readFileSync(join(f.root,'ui/dist/engine-resource-tests-shuffle-partition.wasm'),'utf8'),'NEW ENGINE');
  assert.equal(readFileSync(join(f.root,'ui/dist/engine.wasm'),'utf8'),'PUBLISHED BEFORE ATTEMPT');
 }finally{f.close();}
});

test('implicit Cargo configuration cannot redirect the packaged artifact',()=>{
 for(const target of [undefined,''])for(const configuredTarget of [undefined,'environment-config-target']){
  const f=fixture();try{
   mkdirSync(join(f.root,'.cargo'));
   writeFileSync(join(f.root,'.cargo/config.toml'),'[build]\ntarget-dir = "config-target"\n');
   const r=f.run([],false,{CARGO_TARGET_DIR:target,CARGO_BUILD_TARGET_DIR:configuredTarget});
   assert.equal(r.status,0,r.stdout+r.stderr);
   const call=JSON.parse(readFileSync(join(f.root,'cargo-call.json'),'utf8'));
   assert.equal(call.target,resolve(f.root,'target'));
   assert.equal(call.configuredTarget,call.target);
   assert.equal(readFileSync(join(f.root,'ui/dist/engine.wasm'),'utf8'),'NEW ENGINE');
   assert.equal(existsSync(join(f.root,'config-target')),false);
   assert.equal(existsSync(join(f.root,'environment-config-target')),false);
  }finally{f.close();}
 }
});

test('Cargo failure does not replace the published engine',()=>{
 const f=fixture();try{
  const r=f.run([],false,{FAKE_CARGO_FAIL:'1'});assert.equal(r.status,7,r.stdout+r.stderr);
  assert.equal(readFileSync(join(f.root,'ui/dist/engine.wasm'),'utf8'),'PUBLISHED BEFORE ATTEMPT');
 }finally{f.close();}
});

test('Bash entry point uses the same supported flags and target directory',{skip:process.platform==='win32'?'Bash entry point is checked on Linux':false},()=>{
 for(const args of [[],['--target-dir','alternate-target']]){
  const f=fixture();try{
   const r=f.run(args,true,{CARGO_TARGET_DIR:'environment-target'});
   if(args.length){assert.notEqual(r.status,0);assert.match(r.stderr,/unsupported browser build argument/i);}
   else{assert.equal(r.status,0,r.stdout+r.stderr);assert.equal(readFileSync(join(f.root,'ui/dist/engine.wasm'),'utf8'),'NEW ENGINE');}
  }finally{f.close();}
 }
});
