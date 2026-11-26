## Hosted OPFS spill read copy (2026-11-25)

Reuse the OPFS read slot during synchronous WASI reads. The pinned shim
copies each iovec into linear memory before requesting another read. Staged
export keeps its independent buffer when it awaits a destination write.
All six measured pairs saved time through usable output.
[Issue #90](https://github.com/jsmatfess/chopper/issues/90) ·
[Samples and receipt identities](../../benchmarks/hosted-opfs-spill-read-copy-2026-11-25-summary.json)

### Complete external Uniform Runs

Both cells used plain standalone Uniform shuffle, explicit 512 MiB,
one worker and a 4 MiB serialized CSV cap. The input has a UTF-8 LF
`id,key,payload` header, successive zero-based IDs, eight keys from
`id % 8`, and 20 copies of `Chopper01234` in each payload. The 800,000-row
fixture retains the [previous calibration identity](browser-auto-resource-calibration-2026-11-21.md).
The 3.2-million-row case repeats the shape at 802,088,905 input bytes.

| Rows | Existing seconds, median [range] | Slot view seconds, median [range] | Paired seconds saved, median [range] |
| ---: | ---: | ---: | ---: |
| 800,000 | 14.534 [14.529–14.609] | 14.245 [14.151–14.264] | 0.345 [0.284–0.383] |
| 3,200,000 | 58.582 [58.374–58.677] | 57.009 [56.949–57.051] | 1.573 [1.425–1.626] |

Each cell had one excluded warmup per arm and three alternating measured
pairs. Timing starts at the browser client's Run command and ends after
the completion marker is written and the workspace retires. Outside the
clock, an independent pass checked every ID and field, the caps, output
checksums, manifest and marker, and an empty workspace. The final verifier
counts the manifest along with the CSVs in the marker. The initial 800,000
row summary omitted the manifest from its assertion. Verification of the
original receipts passed after the correction, with the original limits.

### Allocation and traffic

Every job in each cell kept its existing spill topology, with 3 and
10 initial runs respectively and one merge in each case. The bridge
reported 4,659 reads totaling 454,984,352 bytes on the smaller fixture
and 18,676 reads totaling 1,825,004,448 bytes on the larger fixture in
each arm. This is the cumulative payload of the additional JavaScript
copy removed by the change. Engine logical temporary reads and writes were
255,088,890 and 454,984,352 bytes on the smaller fixture and 1,022,888,890 and
1,825,004,448 bytes on the larger fixture. Peak engine reservations matched
across the corresponding arms. Renderer RSS and physical device I/O
were outside the measurement scope.

### Replay

Build the feature-free hosted assets from [c5f9b8b](https://github.com/jsmatfess/chopper/commit/c5f9b8b2e3f2f423ba4965375d46fabbd67ed377).
Rebuild its engine worker with the [slot-view patch](https://github.com/jsmatfess/chopper/commit/7b69ec08243b87a550538c571d95f0ffaff81eb0)
and use identical WASM and storage worker binaries for both arms.
The [swarm driver](../../../ui/tests/benchmark-swarm.ts) supplies the
Run, completion and cleanup boundary. The measurement fixture serves
the same generated CSV in each fresh bundled Chromium 156.0.8078.4
context on one WSL Linux host. The verification uses the browser's real
OPFS and file reads. The proof records the input, asset and driver hashes,
alternating arm order, work counters, resource peaks and output receipt
identities. The frozen elapsed limits require a median cost of at most
0.100 seconds, no pair costing more than 0.500 seconds, and all pairs
favorable with at least 0.100 seconds paired median to claim a gain.
