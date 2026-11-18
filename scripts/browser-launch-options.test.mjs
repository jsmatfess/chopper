import test from 'node:test';
import assert from 'node:assert/strict';
import {contractBrowserLaunchOptions} from './browser-launch.mjs';

test('ordinary launch options remain unchanged without a protected packet',()=>{
 const base={channel:'chrome',args:['--example']};
 assert.equal(contractBrowserLaunchOptions(null,base),base);
});
test('protected identity queries explicitly enable automation without replacing other arguments',()=>{
 const base={channel:'msedge',args:['--example']};
 const options=contractBrowserLaunchOptions({executable:'/selected/browser'},base);
 assert.equal(options.channel,'msedge');assert.equal(options.executablePath,'/selected/browser');
 assert.deepEqual(options.args,['--example','--enable-automation']);
 assert.deepEqual(base.args,['--example']);
 const already={args:['--enable-automation','--example']};
 assert.deepEqual(contractBrowserLaunchOptions({executable:'/selected/browser'},already).args,already.args);
});
