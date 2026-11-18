// Host-side bounded extraction only; no browser launch, bundling or product hooks.
import assert from 'node:assert/strict';
import {mkdir, open, readFile} from 'node:fs/promises';
import {join} from 'node:path';

export const SLICE_BYTES = 512 * 1024;
export const TRANSFER_LIMIT = 1024 * 1024;
const safeName = name => /^(?:(?:region-r[0-7]-allocation-(?:treatment|control)-)?part-[0-9]{8}\.csv|manifest\.jsonl|CHOPPER-COMPLETE\.json)$/.test(name);
export function validateMarker(value, count) {
  assert.deepEqual(value, {complete: true, files: count - 1, engine: 'chopper-browser', version: 1},
    'Invalid completion marker schema/count');
}

export async function extract(page, output, progress = async () => {}, {maxBytes = Infinity} = {}) {
  const files = await page.evaluate(() => window.scaleAcceptance.list());
  assert(Buffer.byteLength(JSON.stringify(files)) <= TRANSFER_LIMIT, 'Unbounded export inventory');
  assert(files.length >= 2 && files.length <= 4098 && new Set(files.map(f => f.name)).size === files.length);
  for (const file of files) {
    assert(safeName(file.name) && Number.isSafeInteger(file.size) && file.size >= 0, 'Unsafe export metadata');
    if (file.name === 'CHOPPER-COMPLETE.json') assert(file.size <= 256, 'Overlarge marker');
  }
  const total = files.reduce((sum, file) => sum + file.size, 0);
  assert(Number.isSafeInteger(total) && total <= maxBytes, 'Export exceeds caller byte ceiling');
  assert(files.some(f => f.name === 'manifest.jsonl') && files.some(f => f.name === 'CHOPPER-COMPLETE.json'));
  await mkdir(output); // Exclusive; retain partial output on failure.
  for (const file of files) {
    const destination = await open(join(output, file.name), 'wx');
    try {
      for (let offset = 0; offset < file.size;) {
        const length = Math.min(SLICE_BYTES, file.size - offset);
        const base64 = await page.evaluate(({name, offset, length}) =>
          window.scaleAcceptance.slice(name, offset, length), {name: file.name, offset, length});
        assert(typeof base64 === 'string' && Buffer.byteLength(JSON.stringify(base64)) <= TRANSFER_LIMIT,
          'Transfer exceeds 1 MiB');
        const bytes = Buffer.from(base64, 'base64');
        assert(bytes.length === length && bytes.toString('base64') === base64, 'Truncated/invalid export slice');
        let written = 0;
        while (written < bytes.length) {
          const result = await destination.write(bytes, written, bytes.length - written);
          assert(result.bytesWritten > 0, 'Export write made no progress');
          written += result.bytesWritten;
        }
        offset += bytes.length;
        await progress({file: file.name, offset});
      }
    } finally { await destination.close(); }
  }
  validateMarker(JSON.parse(await readFile(join(output, 'CHOPPER-COMPLETE.json'), 'utf8')), files.length);
  return files; // Independent Python verifier owns manifest/CSV checks.
}
