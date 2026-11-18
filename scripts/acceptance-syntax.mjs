// Compile selected harnesses and their imports; never evaluate them.
import {createRequire,isBuiltin} from 'node:module';
import {readFileSync,realpathSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {isAbsolute,relative,resolve,sep} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';

export async function checkSyntax(root, scripts) {
 root=realpathSync(root);
 if(!scripts.length)throw Error('Explicit owning scripts required');
 const entries=scripts.map(script=>{
  if(!isAbsolute(script))throw Error('Absolute owning script required');
  const path=realpathSync(script),inside=relative(root,path);
  if(!inside||inside==='..'||inside.startsWith('..'+sep)||isAbsolute(inside))throw Error('Owning script outside selected root');
  return path;
 });
 const require=createRequire(resolve(root,'ui/package.json'));
 const compiler=require.resolve('esbuild');
 const esbuild=require(compiler);
 const packages=new Map(),probes=new Map(),exportsByPath=new Map();
 const namespace='preflight-package-api';
 function packageName(name) {
  return ['playwright','playwright-core','esbuild'].find(packageName=>name===packageName||
   ['index.mjs','index.js',...(packageName==='esbuild'?['lib/main.js']:[])].some(entry=>name===resolve(root,'ui/node_modules',packageName,entry)));
 }
 async function probe(name,selected) {
  const resolved=isAbsolute(name)?realpathSync(name):require.resolve(name);
  if(!probes.has(resolved))probes.set(resolved,(async()=>{
   const api=await import(pathToFileURL(resolved).href);
   if(selected==='esbuild') {
    if(typeof api.build!=='function'||typeof api.stop!=='function')throw Error('Missing esbuild runtime API');
   } else if(['launch','launchPersistentContext','executablePath'].some(method=>typeof api.chromium?.[method]!=='function')) {
    throw Error('Missing '+selected+' chromium runtime API');
   }
   const item={name:selected,resolved,version:require(selected+'/package.json').version,
    exports:Object.keys(api).sort(),sha256:createHash('sha256').update(readFileSync(resolved)).digest('hex')};
   packages.set(resolved,item);
   exportsByPath.set(resolved,item.exports);
   return item;
  })());
  return probes.get(resolved);
 }
 try {
  const result=await esbuild.build({absWorkingDir:root,entryPoints:entries,outdir:'preflight-output',
   bundle:true,write:false,platform:'node',format:'esm',metafile:true,logLevel:'silent',packages:'external',
   logOverride:{'unsupported-dynamic-import':'warning','unsupported-require-call':'warning','import-is-undefined':'error'},
   plugins:[{name:'selected-packages',setup(build){
    build.onResolve({filter:/.*/},async args=>{
     if(isBuiltin(args.path)) {
      const name=args.path.startsWith('node:')?args.path:'node:'+args.path;
      if(!exportsByPath.has(name))exportsByPath.set(name,Object.keys(await import(name)).sort());
      return {path:name,namespace};
     }
     const name=args.path.startsWith('.')?resolve(args.resolveDir,args.path):args.path;
     const selected=packageName(name);
     if(selected)return {path:(await probe(name,selected)).resolved,namespace};
     if(/node_modules[/\\]/.test(name))return {path:resolve(args.resolveDir,name),external:true};
    });
    build.onLoad({filter:/.*/,namespace},args=>({loader:'js',contents:exportsByPath.get(args.path).map((name,index)=>
     `const value${index}=undefined;export {value${index} as ${JSON.stringify(name)}};`).join('\n')}));
   }}]});
  const imports=new Set(Object.values(result.metafile.inputs).flatMap(input=>input.imports.filter(item=>item.external).map(item=>item.path)));
  for(const name of [...imports].sort()) {
   if(isBuiltin(name)||name==='<runtime>')continue;
   const selected=packageName(name);
   if(!selected)throw Error('Unsupported package runtime probe: '+name);
   await probe(name,selected);
  }
  const inputs=Object.fromEntries(Object.entries(result.metafile.inputs).filter(([name])=>!name.startsWith(namespace+':')));
  return {schema:'chopper-acceptance-syntax-v1',status:'passed',node:process.version,esbuild:esbuild.version,compiler,
   packages:[...packages.values()].sort((a,b)=>a.resolved.localeCompare(b.resolved)),entry_points:entries,metafile:{inputs},
   runtime_pending:result.warnings.map(warning=>({id:warning.id,message:warning.text,
    file:warning.location?.file??null,line:warning.location?.line??null}))};
 } finally {await esbuild.stop();}
}

if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
 try {console.log(JSON.stringify(await checkSyntax(process.argv[2],process.argv.slice(3))));}
 catch(error) {
  console.log(JSON.stringify({schema:'chopper-acceptance-syntax-v1',status:'failed',error:String(error.message)}));
  process.exitCode=1;
 }
}
