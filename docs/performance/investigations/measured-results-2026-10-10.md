## Measured results (2026-10-10)

One million generated rows, 128-byte payloads, 140,888,917-byte source; AMD Ryzen AI 9 HX 370, WSL Linux/ext4. Input, spill, and output shared the local filesystem. Three alternating runs per build/case; medians include analysis, compression, and publication, but exclude fixture generation and output verification. All logical output fingerprints matched. These are warm-machine results with uncontrolled OS caching, not cold-storage or billion-row certification.

| Pipeline and resources | Before | After | Speedup | Analysis temp peak before → after |
| --- | ---: | ---: | ---: | ---: |
| Rows only, 32 MiB / 1 worker | 2.24 s | 1.43 s | 1.57× | 201 → 141 MB |
| Balanced ×10, 32 MiB / 1 worker | 2.59 s | 1.77 s | 1.47× | 402 → 342 MB |
| Shuffle → balanced ×10, 32 MiB / 1 worker | 5.39 s | 2.37 s | 2.28× | 635 → 358 MB |
| Shuffle → balanced ×10, 256 MiB / 1 worker | 5.03 s | 2.85 s | 1.76× | 635 → 358 MB |
| Partition → shuffle → balanced ×10, 256 MiB / 4 workers | 6.08 s | 3.39 s | 1.79× | 611 → 454 MB |
| Partition → assign → shuffle → balanced ×10, 256 MiB / 4 workers | 7.10 s | 4.31 s | 1.65× | 611 → 406 MB |
| Shuffle → balanced ×10 → gzip, 256 MiB / 4 workers | 6.53 s | 3.05 s | 2.14× | 635 → 358 MB |
| Shuffle → balanced ×10 → ZIP, 256 MiB / 4 workers | 6.45 s | 3.06 s | 2.11× | 635 → 358 MB |

The 32 MiB shuffle was faster than the 256 MiB shuffle on this fixture; larger sort buffers are not automatically faster. No automatic resource tuner was added.
