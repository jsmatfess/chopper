// Bounded-memory conservation check for the simple, single-line benchmark fixtures.
// Not a general CSV parser: production CSV validation lives in chopper-core.
import { createReadStream } from 'node:fs';
import { readdir } from 'node:fs/promises';
import { createInterface } from 'node:readline';
import { createHash } from 'node:crypto';
import { join } from 'node:path';
const [input, output, countText] = process.argv.slice(2);
if (!input || !output || !countText) throw new Error('usage: node scripts/verify-generated.mjs INPUT OUTPUT_DIR ROWS');
const expected = Number(countText);
const seen = new Uint8Array(Math.ceil(expected / 8));
const hashes = new Uint32Array(expected * 4);
async function lines(path, visit) {
  const reader = createInterface({ input: createReadStream(path), crlfDelay: Infinity });
  let header = true, count = 0;
  for await (const line of reader) {
    if (header) { if (line !== 'id,country,segment,payload') throw new Error('unexpected header'); header = false; continue; }
    const id = Number(line.slice(0,line.indexOf(',')));
    if (!Number.isInteger(id) || id < 0 || id >= expected) throw new Error(`invalid id ${id}`);
    visit(id, createHash('sha256').update(line).digest()); count++;
  }
  return count;
}
const inputRows = await lines(input, (id, digest) => { for (let i=0;i<4;i++) hashes[id*4+i]=digest.readUInt32LE(i*4); });
if (inputRows !== expected) throw new Error('input count mismatch');
let total=0; const counts=[];
for (const name of (await readdir(output)).filter(n=>n.endsWith('.csv')).sort()) {
  const count = await lines(join(output,name), (id,digest)=>{
    const mask=1<<(id%8), index=Math.floor(id/8);
    if(seen[index]&mask) throw new Error(`duplicate id ${id}`); seen[index]|=mask;
    for(let i=0;i<4;i++) if(hashes[id*4+i]!==digest.readUInt32LE(i*4)) throw new Error(`payload changed for ${id}`);
  }); counts.push(count);total+=count;
}
if(total!==expected) throw new Error(`output count ${total} != ${expected}`);
console.log(JSON.stringify({rows:total,files:counts.length,rows_per_file:counts,unique_ids:true,payload_digest_matches:true},null,2));
