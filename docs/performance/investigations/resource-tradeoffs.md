## Resource tradeoffs

The encoded output snapshot counts toward `temp_bytes`. Expanding encodings can require a larger retained snapshot than the old row spool. More memory can reduce spill runs, but is not a guarantee of lower elapsed time: in-memory sorting, cache behavior, compression, and storage can dominate different jobs. `workers` now benefits independent compression as well as sorting; it does not parallelize parsing or merge traversal.

The temporary peak in analysis excludes staged final outputs and can differ from execution's ZIP temporary peak. The working budget is not a process RSS limit. Billion-row shuffle/wide-record scale and storage-device saturation remain unverified; a later narrow-row count stress test is recorded below.
