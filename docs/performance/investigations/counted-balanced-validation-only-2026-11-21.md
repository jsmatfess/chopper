## Counted Balanced validation only (2026-11-21)

The validation-only candidate measured -3.41% elapsed and -5.65% process CPU and missed both retention rules.
The experimental code was removed and the prior compact parser path restored.
[Matched samples, criteria and hashes](../../benchmarks/counted-balanced-validation-only-summary-2026-11-21.json)

| Complete-job measure | Compact count control | Validation-only count |
| --- | ---: | ---: |
| Median elapsed [range] | 38.471 [36.511–40.219] s | 37.159 [32.801–37.564] s |
| Median process CPU [range] | 21.07 [20.84–21.13] s | 19.88 [19.71–20.11] s |
| Median process peak RSS [range] | 5676 [5544–5724] KiB | 5672 [5624–5752] KiB |
| Median peak working reservations [range] | 207467 [207467–207467] bytes | 207479 [207479–207479] bytes |

Pairwise elapsed changes were -2.36%, -7.61%, -10.16%. Pairwise CPU changes
were -4.61%, -4.83%, -6.45%. Control and candidate each ran with one worker
and a 256 MiB engine setting in a 1 GiB hard WSL2/ext4 cgroup with
swap disabled. The 8 GiB fixture splits into eight exact consecutive
parts under a 1200 MiB CSV cap. The complete clock includes process
startup and both validated passes, with independent full-output
verification after timing. Three alternating pairs contribute to
the table. A small preflight pair and full-size warmup pair are
excluded. Every pair has identical logical digest and CSV bytes.
The output writers, second-pass digest and native publication
contracts are common to both builds.

The candidate reused the strict parser state machine with a field
target that returns the row width without packing field bytes.
Both implementations still validate UTF-8 and observe working record
limits. Scratch for fragmented and quoted fields stays charged.
Differential checks covered quoted and fragmented fields, escapes,
CRLF, blank lines, record limits and error context. The intake test
exercised terminal width and admission failure. Both build profiles
passed 35 direct-run tests, including mismatch detection and output
cleanup. The separate earlier component test used the raw-byte proof
prototype, omitted the common write pass and used cached input.
[Earlier component test](partition-routing-and-assignment-tradeoffs-2026-11-18.md)
