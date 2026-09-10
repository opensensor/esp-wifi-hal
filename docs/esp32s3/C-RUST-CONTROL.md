# Reviewed C control and Rust station comparison

The reviewed C station completed ten cycles with **200/200 host replies,
200/200 gateway replies and no duplicates**. Both runs of the same corrected
Rust trace image still lost gateway replies. A final Rust control with ordinary
logging failed during DHCP before traffic, so it does not resolve whether
logging overhead contributes to ping loss. Every attempt is retained below.

## Experiment order and results

All tests used the same secured S3 and AP. C3 station testing was paused during
these S3 runs. The first Rust result is the previously recorded
[sequence-assignment run](STA-SEQUENCES.md). The three additional runs were
planned controls: reviewed C, one byte-identical Rust repeat, and one Rust build
with ordinary logging. None was repeated until it passed.

| Order and profile | Completed cycles | Unique host replies | Gateway replies | Duplicate host receipts | Application result |
| --- | --- | --- | --- | --- | --- |
| A1: Rust c837, packet/MAC trace | 10 | 199/200 | 194/200 | 1 | Final gateway assertion failed |
| B: Reviewed C, normal IDF logging | 10 | 200/200 | 200/200 | 0 | Completed |
| A2: Exact same signed Rust trace image | 10 | 200/200 | 199/200 | 2 | Final gateway assertion failed |
| Rust c837, ordinary logging | 0 | Not attempted | Not attempted | Not measured | Connected cycle 1, then DHCP timed out |

No completed traffic run reported host payload/checksum diagnostics. All ten
first host pings arrived in the C control and traced Rust repeat; no first ping
was excluded or explicitly warmed with ARP.

Each traffic cycle waits one second after DHCP, then exposes a ten-second host
window. The host sends twenty 512-byte pings at 0.2-second intervals, with a
one-second timeout. Only after that window does the device send twenty
512-byte gateway pings configured for a 100 ms interval and one-second timeout.
The C and Rust ping schedulers differ: Rust waits 100 ms after each response or
timeout, while IDF uses its ping-session interval. The configured workload is
aligned, but exact on-air pacing is not asserted identical.

## Reviewable C control changes

The earlier reviewed C image was
`a27a7de2ded83373fd9f31a94cc2d9795da8330ad3c1cd5e782dcfad67f51d94`.
Its source and signed image were preserved. The new control was built from a
copied probe and harness; its `hal_mac.c` is byte-for-byte unchanged.
The [copied-probe patch](c-control-probe.patch) records the complete C application
change against [the existing probe](probe/main/main.c):

- Increase three cycles to ten.
- Add the one-second settle and ten-second host window before gateway traffic.
- Log the gateway sequence on timeout.
- Retain all cycles and require twenty gateway replies in every cycle, plus
  200/200 overall, at the final assertion. The legacy 18/20 gate is not used.

The host harness additionally audits all twenty host replies per cycle and
counts duplicate receipts separately. The patch was applied to a temporary copy
and verified byte-for-byte against the source used for the built C image.

The original C lifecycle remains: `esp_wifi_init`, passive scan, WPA2/DHCP,
traffic, TSF check, disconnect, stop and deinit for every cycle. Power saving
remains disabled. Wi-Fi configuration uses RAM storage. The unchanged IDF
configuration allows PHY calibration data to be stored in NVS. No bootloader,
partition table, eFuse, key, security setting or manual RF tuning was changed.

All ten existing C HAL host-test groups passed. The archive/link audit verified
all 57 function definitions, 30 retained replacement functions, five
ROM-resolved names, and 29 unchanged other archive members. Every C TSF check
passed. Per-cycle heap observations are retained without claiming that this
short run proves a leak-free lifecycle.

## Rust repeat: actual MAC results still matter

The A2 image is exactly the A1 signed image, SHA-256
`b2916434570ff8a2f8202f4e7bd6b83ad004c0e6e703db8018bedaea9932ce82`.
It was copied and hash-checked, not rebuilt. Both `foa` and `foa_sta` resolve to
`c83717eeeeaa8c5b6e53743b868e27de4e55e9be`; smoltcp resolves to
`517222f7318c092d82197e2e68cfccca0f460b09`.

A2 has 508 paired starts/finishes, queue generations 0 through 507, and assigned
sequence numbers 0 through 507 without gaps or repeats. Its final results are:

| Result | Frames |
| --- | --- |
| `Ok(0)` | 477 |
| `Ok(1)` | 23 |
| `Ok(2)` | 4 |
| `Ok(3)` | 2 |
| `Ok(4)` | 2 |
| Error | 0 |

The missing gateway reply is cycle 6, ICMP sequence 11. Its request appears at
the IP transmit boundary, followed by exactly one protected 588-byte frame and
completion: queue 2, generation/assigned sequence 295, **`Ok(2)`**. Its reply
never reaches the IP receive boundary. An ARP request arrives during the wait;
the timeout snapshot shows an empty/incomplete RX head and interrupt status
zero. No transmission-exhaustion warning occurs.

This packet has the same cycle/ICMP sequence label as one A1 loss, but a different
queue generation, timestamp and retry result. The labels alone do not establish
a shared failure cause. All six A1 losses followed `Ok(0)`; A2 adds a loss after
a successful retried transmission.

A2's duplicates have two different observed paths:

- Cycle 3, sequence 9 appears twice at both RX and TX boundaries. The associated
  completions are generations 117 and 118, both `Ok(0)`.
- Cycle 9, sequence 12 appears once at each boundary. Its associated completion
  is generation 426, `Ok(1)`, while the host receives two replies.

The trace observes the final endpoint result and assigned header. It does not
record each physical attempt or its on-air Retry bit. No monitor capture was
made, so these observations do not establish the exact RF duplicate behavior.

## Ordinary-logging control and limits

The last Rust build keeps the same recorded source hashes, dependency pins and
ten-cycle station application. It enables `esp32s3,foa-smoke` with `ESP_LOG=info`,
without `network-trace` or `foa/tx-trace`. The smoltcp pending-response feature
remains enabled through the `foa-smoke` dependency. The logs confirm zero packet
and MAC trace events.

That image connected in cycle 1 but reached the unchanged fifteen-second DHCP
timeout. It attempted no host or gateway pings. The failed first attempt was
retained and not repeated. It leaves the effect of diagnostic overhead on ping
loss unresolved; it is also an additional connection-lifecycle failure needing
its own diagnosis. The S3 was left at this panic, before the planned disconnect,
and the serial test process exited.

C fully tears Wi-Fi down each cycle; Rust retains the initialized PHY and driver
across reconnects. C uses IDF/lwIP, its usual station MAC and GCC 14.2; Rust uses
FoA/embassy/smoltcp, a randomized station MAC and the existing Rust/Xtensa
build. Their calibration lifecycles and diagnostic overhead differ. These
controls compare complete applications under nearby network conditions rather
than isolating a single implementation variable. They reproduce the clean C
result and preserve concrete Rust failures without proving their cause.

Image hashes:

| Profile | Signed application SHA-256 |
| --- | --- |
| Reviewed C control | `9d24b745ee7a57629f39e1c3e3c0d4a905b2e0b4cca44b1c04c225aaeb492553` |
| Rust trace, both A1 and A2 | `b2916434570ff8a2f8202f4e7bd6b83ad004c0e6e703db8018bedaea9932ce82` |
| Rust ordinary logging | `2f6c878a1e658a030ae4f318fef050bc07a98291b8e4e6c61eae8c8c0a0b3d96` |

[Machine-readable evidence](c-rust-control-validation.json) contains source and
image hashes, every cycle, the C build/link checks, sequence lists, paired MAC
outcomes, loss/duplicate correlations, and the ordinary-logging failure.
Private addresses, credentials, raw logs and firmware are excluded.
