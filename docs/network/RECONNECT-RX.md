# Reconnect response queues and RX exhaustion

The C3/S3 receive queue could reload hardware onto a completed descriptor that
software had not yet consumed. Dequeuing and appending buffers now preserve the
hardware cursor while it is active. An exhausted chain restarts at the first
incomplete descriptor, skipping unread completions. The consumer also checks
for exhaustion, covering hardware caching a null tail just before an append.
Completion reads and publication of descriptor links use volatile accesses and
acquire/release fences. Empty queues clear the hardware base; returned buffers
have no links to borrowed descriptors. ESP32/S2 retain their previous restart
policy and have compile-only coverage.

An S3 diagnostic captured SIG_LEN changing from 300 to 20 and then 14 while the
same descriptor still reported a completed 344-byte buffer. The receive filter
rejected the overwritten header and delivered another buffer. The original
identity assertion caught this at cycles 51 and 21 in separate trials; another
trial timed out waiting for RX at cycle 160. Those failures remain in the
validation record. The host regression first failed on a reload of an unread
completion; it now verifies cursor preservation, exhaustion restart, pending
frame preservation and out-of-order buffer returns using the production queue.

The network queue was a separate loss source. With eight pending-response slots,
an ordinary S3 reconnect trial queued ten echo replies during an ARP delay,
evicted two, and returned 18/20 host pings in cycle 13. Instrumented counts were
exactly ten enqueues, eight dispatches and two evictions for that cycle. This
establishes the immediate loss mechanism; Ethernet capture does not locate the
earlier failed ARP exchanges on the radio path.

The station examples select 32 pending-response slots to accommodate their
five-echoes-per-second workload over the existing five-second expiry window.
The linked static RAM increase is 36,864 bytes on each chip, including metadata.
smoltcp's library default remains eight slots, and packet expiry and neighbor
validation are unchanged. This is finite buffering: higher rates, longer
outages, multiple peers or TX congestion can still lose packets. Applications
should select capacity for their RAM and traffic budget.

Enable `neighbor-probe` in the examples for aggregate counts once per completed
cycle. The fifteen counters are documented in the pinned OpenSensor smoltcp
`tests/PENDING-PROBE.md`. There is no packet logging in this probe. The optional
`rx-probe` exposes queue addresses and completion metadata; hardware can advance
between reads, so its snapshots are not atomic. `RX_SMOKE_CYCLES` selects 1–1000
exhaustion/recovery repetitions for `wifi_smoke`, defaulting to one. At hardware
exhaustion the probe identifies the completed tail through LAST, because BASE
is a reload address and need not equal the software queue head.

Host checks:

```sh
sh docs/esp32s3/tests/run-rust-tests.sh
cargo test --locked --target x86_64-unknown-linux-gnu \
  --manifest-path docs/network/tests/pending-response-repro/Cargo.toml --features burst32
```

The burst test sends 25 independent 512-byte echo requests at 200-ms intervals,
withholds ARP until 4,999 ms, and requires all replies in order with intact
payloads and valid checksums. The smoltcp default-capacity test separately
requires exactly two evictions and replies 3–10 for ten requests and a 2,030-ms
ARP delay. Neither test extends the five-second expiry deadline.

The eight-slot S3 station baseline completed 50 reconnects with 998/1,000 host
and 1,000/1,000 gateway replies, no duplicates and no capture socket drops.
Separate two-cycle experiments on both S3 and C3 omitted their first two ARP
replies during cycle two. On each board, eight slots produced exactly two
evictions and 38/40 host replies; 32 slots retained all ten delayed replies and
returned 40/40 host replies. All four trials returned 40/40 gateway replies. The omission hook is a separate private
build, absent from the published driver and normal station images.

Each board passed 300 final-source RX exhaustion/recovery cycles. An earlier
S3 prototype also passed 300 cycles. Eight DMA host regressions pass per chip,
along with the existing HAL, PHY, allocation, retry and neighbor tests. The C3
probe-disabled build and ESP32/S2 release checks also pass. Packet host tests
require Rust 1.91 or newer; local validation used the installed `+esp` toolchain.

The corrected 50-reconnect station tests are still in progress. The machine-readable `reconnect-rx-validation.json` records every completed and failed trial, image/source hashes, queue counts,
reconnect totals and capture statistics. Private firmware, credentials, signing
keys, serial logs and captures are not publication artifacts. Only the existing
application slots are used: signed S3 at 0x20000 and C3 at 0x10000.
