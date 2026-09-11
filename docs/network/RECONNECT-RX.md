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

With the DMA cursor fix already applied, the eight-slot S3 station baseline
completed 50 reconnects with 998/1,000 host
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

The published source then completed 50 reconnects on each board. Each returned
999/1,000 host and 1,000/1,000 gateway echoes with zero evictions, expiries,
duplicates or capture socket drops. The residual losses are C3 cycle 3,
sequence 9 and S3 cycle 21, sequence 14. Neither cycle logged a TX failure or
crypto/replay rejection. The timing snapshots did not locate the missing frames. These are not explained by the
ARP queue change, and the lossless station gate has **not** passed. Do not treat
a successful reconnect or a passing repeat as erasing either loss.

Further private observation records echo sequence masks at raw RX, VIF queue
submission, network-buffer submission and the Ethernet adapter. Per-cycle
counters identify the exact echo sequence if a VIF or network-buffer overflow
rejects it; no packet content or identities are exported. The follow-up completed 50 reconnects on each board:

| Board / trial | Reconnects | Host replies | Gateway replies |
| --- | ---: | ---: | ---: |
| C3 normal, corrected source | 50 | 999/1,000 | 1,000/1,000 |
| C3 with receive/echo observation | 50 | 1,000/1,000 | 1,000/1,000 |
| S3 normal, corrected source | 50 | 999/1,000 | 1,000/1,000 |
| S3 with receive/echo/restart observation | 50 | 1,000/1,000 | 1,000/1,000 |

Both observed trials accounted for every host sequence at raw RX and at the
Ethernet adapter, and every reply submitted back to the adapter. They had no
VIF/network-buffer overflow, invalid header, checksum error, duplicate or
capture socket drop. S3 never entered the exhausted-chain restart helper during
this station trial; this counter excludes initial/empty-list setup. Normal
accepted duplicate/replay rejection of unrelated traffic is not an echo loss.

The two earlier normal-run losses remain unexplained. Instrumentation can change
timing, and a clean observed repeat does not establish that they are fixed.
The bounded validation is complete; the lossless normal-station gate remains
open. Locating a recurrence without extra MCU instrumentation requires peer/AP
or on-air evidence. No additional receive-queue scheduling change is justified
by these observations alone. The machine-readable [`reconnect-rx-validation.json`](reconnect-rx-validation.json) records every completed and failed trial, image/source hashes, queue counts,
reconnect totals and capture statistics. Private firmware, credentials, signing
keys, serial logs and captures are not publication artifacts. Only the existing
application slots are used: signed S3 at 0x20000 and C3 at 0x10000.
