import assert from 'node:assert/strict';
import test from 'node:test';
import {readFile,mkdtemp,writeFile,chmod,rm} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {build} from 'esbuild';
const bundle=await build({entryPoints:['src/run-command.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const {runArguments,runCommand,defaultCommandPlatform}=await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);
const fixture=JSON.parse(await readFile('../crates/chopper/tests/fixtures/run-cli.json','utf8'));
test('all Job settings generate the argv fixture consumed by the native parser',()=>{
 assert.deepEqual(runArguments(fixture.job),fixture.args);
 assert.equal(runCommand(fixture.job).usesJson,false);
 assert.equal(fixture.args.filter(arg=>arg.startsWith('--step=')).length,7);
});
test('PowerShell literals preserve quotes, interpolation and delimiters as data',()=>{
 const command=runCommand(fixture.job).command;
 assert.ok(command.includes(String.raw`'--input=C:\O''Brien\$(touch ignored) input.csv'`));
 assert.ok(command.includes(`'--column=-q''"; $(ignored)'`));
});
test('oversized jobs use JSON instead of an unusable Windows command',()=>{
 const job=structuredClone(fixture.job);job.operations=[{type:'partition',columns:['x'.repeat(25000)]}];
 assert.deepEqual(runCommand(job),{command:String.raw`.\chopper.exe run --config .\chopper-job.json --yes`,usesJson:true});
});
test('NUL-containing column names require JSON because native argv cannot represent them',()=>{
 const job=structuredClone(fixture.job);job.operations=[{type:'partition',columns:['a\0b']}];
 assert.equal(runCommand(job).usesJson,true);
});

test('platform defaults are a hint and platform-specific JSON fallback uses native paths',()=>{
 assert.equal(defaultCommandPlatform('Win32'),'windows');assert.equal(defaultCommandPlatform('Windows'),'windows');assert.equal(defaultCommandPlatform('MacIntel'),'macos');assert.equal(defaultCommandPlatform('macOS'),'macos');assert.equal(defaultCommandPlatform('Linux x86_64'),'linux');
 const job=structuredClone(fixture.job);job.operations=[{type:'partition',columns:['x'.repeat(25000)]}];
 for(const platform of ['linux','macos'])assert.deepEqual(runCommand(job,platform),{command:'./chopper run --config ./chopper-job.json --yes',usesJson:true});
});
test('Linux and macOS shell previews preserve the complete argv in a real POSIX shell',{skip:process.platform==='win32'},async()=>{
 const dir=await mkdtemp(join(tmpdir(),'chopper-cli-'));
 try{
  const executable=join(dir,'chopper');await writeFile(executable,'#!/usr/bin/env node\nconsole.log(JSON.stringify(process.argv.slice(2)))\n');await chmod(executable,0o755);
  for(const platform of ['linux','macos']){
   const command=runCommand(fixture.job,platform).command;assert.ok(command.startsWith('./chopper run '));
   const actual=JSON.parse(execFileSync('sh',['-c',command],{cwd:dir,encoding:'utf8'}));assert.deepEqual(actual,fixture.args);
  }
 }finally{await rm(dir,{recursive:true,force:true});}
});
