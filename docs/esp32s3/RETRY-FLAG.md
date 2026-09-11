# S3 Retry-bit restoration: first hardware result

The first prescribed S3 run with the reviewed Retry-bit restoration received
**200/200 host replies and 198/200 gateway replies**, with zero host duplicates.
All ten cycles ran, but the final gateway assertion failed. This result preserves
the remaining loss; it does not establish a complete reliability fix.

## Source and test identity

The driver change is
`d73b32d5da747a62c72beeea5e342d21785c844c`, integrated as `27945ae`.
The tested `esp-wifi-hal/src/async_driver.rs` exactly matches the production
source SHA-256:

```text
b838b0b3883d6ba0b2b563ec63eaf556cf2f7e1c6812d7d0109ac6d43b19a9f3
```

After a MAC protocol error, the driver now sets the Retry bit for later attempts
of that queued frame. Channel-access failure alone does not set it or clear an
existing Retry bit. Sequence assignment remains before the retry loop. See
[the source review and regressions](../network/MAC-RETRIES.md).

All eleven host regressions passed in both debug and release modes. The harness
extracts the production retry implementation; the tests cover lost ACKs,
channel-access failures, rate fallback, exhaustion, cleanup, raw callers and
buffer reuse. Hardware telemetry remains a separate check.

This build retains the earlier traced station profile:

- FoA and foa_sta: `c83717eeeeaa8c5b6e53743b868e27de4e55e9be`.
- smoltcp: `517222f7318c092d82197e2e68cfccca0f460b09`.
- Features: `esp32s3,network-trace,foa/tx-trace`.
- Log filter: `info,smoltcp=trace,embassy_net=debug,foa::tx_queue=trace,foa_sta=info`.
- Ten cycles, a one-second post-DHCP settle, then a ten-second host window with
  twenty 512-byte pings at 0.2-second intervals. Twenty 512-byte gateway pings
  follow, with the same 100 ms delay and one-second response timeout as before.

The first host ping is included, with no explicit ARP warm-up. C3 station traffic
was paused. The compared source hashes and dependency pins are unchanged except
for `async_driver.rs`. No PHY or trace implementation change was added.
The signed application SHA-256 is
`7f4428efa0ec7ce816b9804b2b358c07f3ad1a172bfa25b65475f11121c76fa4`.
Only that signed application was written at `0x20000` on the existing secured S3.

## Completion and loss audit

There are exactly **505 starts and 505 finishes**, all paired by queue and
generation. Every pair uses hardware queue 2; generations and assigned sequences
advance from 0 through 504 without gaps or repeats. There are no unmatched events
or pair identity mismatches.

| Actual endpoint result | Frames |
| --- | --- |
| `Ok(0)` | 479 |
| `Ok(1)` | 20 |
| `Ok(2)` | 4 |
| `Ok(3)` | 1 |
| `Ok(4)` | 1 |
| Error | 0 |

There are no host duplicates, no repeated host request/reply sequences at the
FoA/embassy boundary, no host payload/checksum diagnostics, and no
transmission-exhaustion warnings. All ten first host pings arrived.

The two missing gateway replies have the following correlations:

| Cycle / ICMP sequence | Queue generation / assigned sequence | MAC result | ARP receives during wait |
| --- | --- | --- | --- |
| 8 / 2 | 384 | `Ok(0)` | 3 |
| 10 / 19 | 502 | `Ok(2)` | 2 |

In each case, the request reaches the IP transmit boundary, followed by exactly
one protected 588-byte frame start and its matching finish before timeout.
There is no other FoA start in that window. The matching reply never appears at
the receive boundary. Both timeout snapshots show an empty/incomplete RX head,
control `0x80000000`, flags `0x80000640`, and interrupt status zero. Other ARP
traffic continues to reach receive during both waits.

The first loss followed a successful initial transmission; the second followed
a successful transmission after two retries. These outcomes keep the remaining
receive/delivery problem separate from reported retry exhaustion. The completion
trace does not record every physical attempt or its on-air Retry bit. No monitor
capture was made, so this run alone cannot establish the exact RF behavior.

The preceding [C/Rust control comparison](C-RUST-CONTROL.md), both earlier traced
Rust failures, and the ordinary-logging DHCP failure remain intact. Zero
duplicates in this bounded run does not prove that all duplicate paths are fixed.
No automatic retry was performed. The application disconnected after cycle 10,
then panicked at its final loss assertion; the serial process closed and the
hardware window was released for C3 testing.

[Machine-readable evidence](retry-flag-validation.json) records every cycle,
source/image hashes, sequence lists, paired completions, retry histograms and
both lost-packet correlations. Raw logs, network addresses, credentials and
firmware remain private.
