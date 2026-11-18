import assert from 'node:assert/strict';
import test from 'node:test';
import {build} from 'esbuild';
const bundle=await build({entryPoints:['src/size-units.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const {sizeUnits,parseAmount,formatAmount}=await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);
test('unit changes round-trip exact byte amounts, including the largest safe integer',()=>{
 for(const value of [1,1025,123456,8388608,268435456,1099511627776,Number.MAX_SAFE_INTEGER])for(const unit of Object.keys(sizeUnits))assert.equal(parseAmount(formatAmount(value,unit),unit),value,`${value} in ${unit}`);
 assert.equal(formatAmount(268435456,'GiB'),'0.25');assert.equal(formatAmount(8388608,'MiB'),'8');
});
test('decimal and binary units remain distinct and fractional amounts must resolve to whole bytes',()=>{
 assert.equal(parseAmount('1.5','MB'),1500000);assert.equal(parseAmount('1.5','MiB'),1572864);assert.equal(parseAmount('.25','GiB'),268435456);assert.equal(parseAmount('','MiB'),null);
 for(const [text,unit] of [['0','B'],['-1','MiB'],['0.1','B'],['9007199254740992','B'],['abc','MB'],['1','unsupported']])assert.throws(()=>parseAmount(text,unit));
});
