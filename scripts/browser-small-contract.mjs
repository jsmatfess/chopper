// A validation-runner step entry point, never a standalone acceptance controller.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {resolve,basename} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {validatePacket} from './browser-small-observer.mjs';
assert.equal(process.argv.length,3,'Usage: node scripts/browser-small-contract.mjs ABSOLUTE_PACKET.json');
const path=resolve(process.argv[2]),packet=JSON.parse(await readFile(path,'utf8'));
validatePacket(packet,packet.channel,packet.argv);
const harness=resolve(fileURLToPath(new URL('.',import.meta.url)),basename(packet.argv[0]));
assert.equal(packet.argv[0],harness,'Owning harness must be in this test checkout');
process.env.CHOPPER_BROWSER_CHANNEL=packet.channel;
process.env.CHOPPER_SMALL_CONTRACT_REQUIRED='1';
process.env.CHOPPER_SMALL_CONTRACT_PACKET=path;
// The actual owning harness sees exactly the approved flags. No child or shell.
process.argv=[process.execPath,...packet.argv];
await import(pathToFileURL(harness).href);
