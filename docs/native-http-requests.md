# Native HTTP request deadlines and shutdown

> Historical contract: the native server and vendored HTTP transport are retired
> from the current CLI/hosted product. Source references below identify the old
> implementation, retained only in the [private archive boundary](history/public-source-boundary.md).

Issue [#154](history/prior-issues.md#issue-154) changes native server
transport/dispatch only. Hosted workers and native engine/publication policy keep
their separate contracts. Implementation:
`crates/chopper/src/server.rs` and `vendor/tiny_http-0.12.0/CHOPPER.md`
in the private historical source archive.

The native server accepts at most **32 live connections** (including incomplete
headers and queued requests), with **32 fixed transport workers**, and at most
**four body handlers**, including columns, sniff and picker. There is no waiting
body-handler queue. Excess body handlers receive 503; excess transport connections
receive an empty 503 and close. Socket write waits are at most 200 ms per write
(100 ms for transport excess). One HTTP request is served per connection;
responses advertise `Connection: close`. Headers are limited to 64 KiB; chunk-size lines, including ignored extensions,
are limited to 1 KiB with fixed parser storage. Unsupported HTTP versions release
their connection slot after the 505 response.
HTTP framing/socket/stack/runtime allocations are bounded by these counts, but
are not newly charged to engine working-memory admission or a complete RSS cap.

The timeout is set on the socket that performs each read, rather than a control
clone: native Windows diagnosis found no timeout propagation between those
cloned handles in the recorded environment. This identifies the failing seam,
not a general Windows/Rust implementation cause.

Every connection has a **five-second absolute read deadline from acceptance**,
including header reads, fixed/chunked bodies, small bodies, inspection/picker
body reads and RawBody's denial drain. Partial progress never renews it. Timed-out
bodies fail and release admitted owners; early EOF in a fixed body fails even
when its prefix happens to be valid JSON. A timeout can return 400/408 or close
the transport; clients must not assume a JSON response after transport failure.
Oversized declarations still reject before `100 Continue`. Rejection does not
invoke the dependency's old implicit fixed-body drain. The explicit admission
denial drain still releases wire bytes/grants first, drains only the remaining
1 MiB-plus-one byte allowance, and preserves the original denial error.

Status, cancel, defaults and prepared confirmation stay on dispatch and do not
read request bodies. Four stalled submissions cannot occupy that lane. Tiny
local socket controls require **each status/cancel/confirmation or excess-handler
response within two seconds** and **signal shutdown within three seconds**.
These are conservative acceptance thresholds for the controlled local fixtures,
not service latency promises under arbitrary CPU/filesystem load. At the hard
transport cap, new connections (including controls) receive bounded 503 rather
than allocating more handlers; header-only saturation frees capacity on the same
five-second deadline. No per-route availability is claimed against unlimited
connection/header floods.

Ctrl+C first stops transport admission and interrupts all owned sockets, then
requests Jobs shutdown. The dispatch loop rechecks stopping after dequeue.
Shutdown closes the picker lifecycle, cancels active/ready work, waits for
job-owned cleanup, and joins all four possible body handlers. HTTP deadlines do
not bound arbitrary local filesystem/device calls made after decoding (including
inspection), OS scheduling or cleanup failure; do not force-detach owners or
report incomplete output as successful to manufacture a timeout pass. Jobs
retains one-active-job arbitration, immutable ready snapshots, admitted
wire/decoded/typed owners, confirmation and cancellation/publication precedence.

## Reproducible tiny controls

Parent Linux qualification passed formatting, Clippy, workspace tests, a native
build and the real socket controls below. A separately retained pre-fix binary
reproduced blocked status and signal shutdown. Parent review controls also cover
repeated unsupported HTTP versions without slot exhaustion and oversized chunk
framing rejection before body admission. Native Windows execution, active-engine
OS-signal qualification and exact candidate delivery/release gates remain unrun;
Linux passes do not establish that coverage.

After parent admission, from the repository root:

```sh
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace --locked
cargo build --locked -p chopper
python3 scripts/test-server-request-deadline.py --binary target/debug/chopper --logs scratch/http154-fixed-linux
```

Use the actual target directory if configured differently. Run the same Python
control against the matching native Windows executable from an attached console
(`CTRL_BREAK_EVENT` is sent to its new process group); retain separate log paths
and exact binary hashes. The script records binary identity and raw server
stdout/stderr, uses three CSV records, and asserts four-handler saturation,
responsive controls, small/large fixed and chunked expiry, slow trickling,
authentication, profile/prepare/confirm/direct output parity, ready snapshot
preservation, signal exit and prepared-file cleanup. Existing
`server::jobs::lifecycle_tests` cover active work cancellation/cleanup and
successful-publication precedence at deterministic worker seams. New
`server::transport_tests` force zero-admission fixed/chunked denial drains and
check both deadline and shutdown interruption, plus the transport connection cap.
The added lifecycle socket control pauses an actual three-row preparation at its
progress callback, interrupts a held socket and requests shutdown, then asserts
cancelled state and owned-file cleanup. Actual active-engine OS-signal acceptance
remains to be recorded on native Linux/Windows.

For the historical failure, use a separately retained pre-fix binary (never
replace it), a fresh log directory and `--old-control`:

```sh
python3 scripts/test-server-request-deadline.py --binary /path/to/pre-fix/chopper --logs scratch/http154-old-linux --old-control
```

It requires the authenticated 100,000-byte/first-byte body to block independent
status for two seconds and SIGINT shutdown for three seconds, then kills the
owned control process in cleanup. No old/fixed runtime pass is claimed until the
parent retains those logs. The old candidate at 6069cef and its evidence/assets
remain historical; changed server bytes require a newly selected release
candidate and matching native artifact acceptance before publication (#91).

Bounded reads use waits of at most 100 ms on the actual reader and check a sticky
shutdown flag between waits. Each wait remains capped by the original absolute
read deadline. Native Windows qualification found that socket shutdown returned
success without interrupting a pending read, including with a shared handle.
The unbounded transport retains its original behavior.
