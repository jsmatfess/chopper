'use strict';
// The preparation-only probe never imports the browser driver or launches it.
const {readFileSync}=require('node:fs');
const {Script}=require('node:vm');
const {resolve}=require('node:path');
const assert=require('node:assert/strict');
assert.equal(process.argv.length,3);
for(const name of ['driver.cjs','hosted.cjs'])new Script(readFileSync(resolve(__dirname,name),'utf8'),{filename:name});
const api=require(process.argv[2]);
for(const name of ['launch','launchPersistentContext','executablePath'])assert.equal(typeof api.chromium?.[name],'function');
console.log(JSON.stringify({status:'passed',node:process.version,playwright:require(resolve(process.argv[2],'package.json')).version,launch:false}));
