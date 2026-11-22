## Exact resident buckets at 2 GiB (2026-11-21)

Archive the resident bucket experiment unapplied after the 2 GiB
continuation screen. The bucket route saved 4.1% CPU relative to the
lower-CPU control. Elapsed was 8.2% higher than the faster control.
Managed temporary reads, writes and file counts were equal. This one
triplet stopped expansion under the declared screen rule.
[Screen, retry and pressure evidence](../../benchmarks/exact-resident-buckets-2026-11-21.json)

| Complete job | Current Auto | Explicit Sort | Resident buckets |
| --- | ---: | ---: | ---: |
| Elapsed | 45.430 s | 42.524 s | 46.008 s |
| Process CPU | 22.21 s | 22.67 s | 21.29 s |
| Peak RSS | 53,336 KiB | 53,540 KiB | 53,024 KiB |
| Peak tracked reservations | 33,964,680 bytes | 33,964,680 bytes | 33,964,818 bytes |
| Managed temporary reads | 9,311,944,425 bytes | 9,311,944,425 bytes | 9,311,944,425 bytes |
| Managed temporary writes | 9,236,595,928 bytes | 9,236,595,928 bytes | 9,236,595,928 bytes |

The plain source contains 8,388,608 records across 128 partitions.
Each retained parent fits individually at the 128 MiB engine setting.
The complete source exceeds the hard 1 GiB Linux/WSL2 cgroup, with
swap off, one worker and a 256 MiB shared ledger. There are eight
equal exact allocations and one named zero per parent. Every bucket
parent activates without retry. Explicit Sort runs first, Auto next
with uncontrolled backing cache. Exact seeded output, every
field and source ID, per-parent quotas, encounter order, strict caps
and logical Analysis agree. This is an early futility decision for
the candidate with these controls. It provides one observation per arm.

Current Auto and Sort already start exact assignment resident. The
candidate removes comparison sorting with stable quota-sized buckets,
transfers existing row ownership, and retains admitted child lineage.
It releases each bucket's descriptor capacity during emission. A
70,003-row pressure test with eight parents shows the effect at one
shared boundary. When the 30 MiB peer request arrives at serialized
row 65,536 in a 32 MiB pool, buckets admit it and publish. Auto and
Sort deny that peer request and publish. At operation entry, the
same request denies all three jobs. A 28 MiB entry request completes
in all three. This locates a phase-specific headroom gain. The full
job counters show a comparable tracked peak and RSS.

Typed denial at retained reader construction rolls back once to
the original exact operation. Cancellation wins over retry, and
a sink denial after one row stays terminal. In the separate 65,537-row
oversize parent at 32 MiB job memory, the actual candidate retries
once with 2,883,584 additional logical read bytes and identical writes
and file count. Both paths publish exact output. The older
probabilistic resident retry and explicit Sort traffic result remains
distinct from this exact quota and stable scattering experiment.
[Historical independent events trial](independent-events-allocation-transfer-2026-11-03.md)
[Archived experiment patch](../../benchmarks/exact-resident-buckets-2026-11-21.patch)
