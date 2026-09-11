# S3 strict receive packet-number check: first hardware result

The first prescribed S3 run after the receive packet-number correction received
**200/200 host replies and 199/200 gateway replies**, with zero duplicates. All
ten cycles ran, but the final gateway assertion failed. The run demonstrates
that the corrected gate still supports repeated WPA2 connections and traffic;
it does not establish a complete packet-loss fix.

## The isolated dependency change

Both `foa` and `foa_sta` select
`39f44767178462e0c5e02aa8a8bd220c8cfd1bd3`, whose parent is the previously tested
`c83717eeeeaa8c5b6e53743b868e27de4e55e9be`. The production source change is:

```diff
-        let valid = replay_counter <= packet_number;
+        let valid = replay_counter < packet_number;
```

The downloaded Cargo checkout's `foa_sta/src/rsn.rs` matches the reviewed SHA-256:

```text
009b00932f84529f2f950d2a5690e105b97d543600c99035aeea926326695554
```

The [FoA review and host regression](https://github.com/opensensor/FoA/blob/39f44767178462e0c5e02aa8a8bd220c8cfd1bd3/tests/STA-REPLAY.md)
cover actual production replay-state and receive-routing methods. Seven tests
passed in debug and release during review; the unchanged earlier implementation
failed five of them. Those tests establish rejection of a repeated protected
packet number independently of this radio test. Their documented limits,
including future QoS/TID handling and GTK replay initialization, still apply.

The S3 retains the reviewed [Retry-bit restoration](RETRY-FLAG.md), with
`async_driver.rs` SHA-256
`b838b0b3883d6ba0b2b563ec63eaf556cf2f7e1c6812d7d0109ac6d43b19a9f3`.
The local firmware source hashes are unchanged except for the dependency pins
and lockfile; smoltcp remains at
`517222f7318c092d82197e2e68cfccca0f460b09`.
No PHY change, new trace instrumentation, RF adjustment, or security change was
added for this run.

The signed application SHA-256 is
`1a496134acfba484c675a6698a7966d4848a772bfb0a352e3e5b9e9cc5be5e55`.
It was flashed only at `0x20000` on the existing secured S3. The preceding
Retry-only image and its failures remain preserved.

## Unchanged test profile

The build enables `esp32s3,network-trace,foa/tx-trace` and logs with
`info,smoltcp=trace,embassy_net=debug,foa::tx_queue=trace,foa_sta=info`.
C3 station testing was paused during the S3 window.

Each of ten cycles connects, obtains DHCP, waits one second, then provides a
ten-second host window for twenty 512-byte pings at 0.2-second intervals. The
first ping is counted without explicit ARP warming. The device then sends twenty
512-byte gateway pings with the existing 100 ms delay and one-second response
timeout before disconnecting. All ten first host pings arrived.

## Completion and remaining loss

There are exactly **507 starts and 507 finishes**, paired by queue and generation
without mismatches. Queue 2 generations and assigned sequences advance from 0
through 506, with every sequence delta equal to one.

| Actual endpoint result | Frames |
| --- | --- |
| `Ok(0)` | 470 |
| `Ok(1)` | 34 |
| `Ok(2)` | 3 |
| Error | 0 |

The host received no duplicates and reported no payload/checksum diagnostics.
No repeated host request/reply or gateway request/reply sequences appear at the
FoA/embassy boundaries. There are no transmission-exhaustion warnings.

The one missing gateway reply is **cycle 1, ICMP sequence 2**. Its request reaches
the transmit boundary at 18,165,494 microseconds. Exactly one protected 588-byte
frame follows before timeout: queue 2, generation/assigned sequence **30**, with
final result **`Ok(0)`**. Its matching reply never reaches the receive boundary.
No other FoA start, ARP packet or ICMP receive appears in that interval. The
timeout snapshot shows an empty/incomplete RX head, control `0x80000000`, flags
`0x80000640`, and interrupt status zero.

This is a loss after a reported successful first transmission, without a
reported retry exhaustion. The trace does not capture every over-air attempt,
peer application processing, receive CCMP packet numbers or replay-rejection
counts. It therefore cannot show that a repeated packet number was encountered
or rejected during this run. Zero observed duplicates is a bounded observation,
not proof that every duplicate-delivery path is resolved.

The [C/Rust control comparison](C-RUST-CONTROL.md), earlier traced Rust losses,
and ordinary-logging DHCP failure remain intact. No automatic repeat was made.
After cycle 10 disconnected, the final gateway assertion panicked; the serial
process closed and the S3 hardware window was released for C3 testing.

[Machine-readable evidence](rx-pn-validation.json) includes exact source and
image hashes, every cycle, complete sequence lists, paired MAC results, boundary
duplicate counts and the lost-packet correlation. Private addresses, credentials,
raw logs and firmware are excluded.
