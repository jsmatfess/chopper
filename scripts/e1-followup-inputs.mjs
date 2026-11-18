// Bounded source inventory works in both a checkout and an ignored staged mirror.
import assert from 'node:assert/strict';
import {lstat,readdir,readFile,realpath} from 'node:fs/promises';
import {join,relative,isAbsolute,resolve} from 'node:path';
import {createHash} from 'node:crypto';
const required=['Cargo.toml','Cargo.lock','ui/package.json','ui/package-lock.json','ui/tsconfig.json'];
const directories=['crates','scripts','ui/src','ui/tests','vendor/zip-2.4.2','vendor/zstd-sys-2.1.1'];
export async function sourceIdentity(root){
  assert(isAbsolute(root),'absolute source required');
  const paths=[...required];
  async function walk(rel){
    const full=join(root,rel),s=await lstat(full);
    assert(!s.isSymbolicLink(),'source link refused: '+rel);
    if(s.isDirectory()){const names=await readdir(full);assert(names.length,'empty source directory: '+rel);for(const n of names.sort())await walk(rel+'/'+n);}
    else {assert(s.isFile(),'non-file source: '+rel);paths.push(rel);}
  }
  for(const dir of directories)await walk(dir);
  try{await walk('.cargo');}catch(e){if(e.code!=='ENOENT')throw e;}
  assert(paths.includes('scripts/benchmark-e1-followup.mjs')&&paths.includes('ui/tests/e1-followup.ts'),'incomplete harness inventory');
  const rows=[];for(const path of [...new Set(paths)].sort()){
    const s=await lstat(join(root,path));assert(s.isFile()&&!s.isSymbolicLink(),'source file required: '+path);
    const b=await readFile(join(root,path));rows.push({path,size:b.length,sha256:createHash('sha256').update(b).digest('hex')});
  }
  return rows;
}
export async function ownedFile(owner,file){
  assert(isAbsolute(file)&&resolve(file)===file,'canonical absolute artifact required');
  const actual=await realpath(file),base=await realpath(owner),r=relative(base,actual);
  assert(r!==''&&!r.startsWith('..')&&!isAbsolute(r),'artifact escaped invocation');
  assert.equal(actual.toLowerCase(),resolve(file).toLowerCase(),'artifact link refused');
  assert((await lstat(actual)).isFile(),'artifact must be a file');return actual;
}
