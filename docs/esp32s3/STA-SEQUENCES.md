# S3 station sequence assignment and remaining packet loss

The S3 trace confirms that FoA's station sequence correction works, while a
single ten-cycle hardware run still loses packets. This is a failed reliability
run with useful transmission evidence, not a clean result obtained by retrying.

Both `foa` and `foa_sta` use OpenSensor FoA commit
`c83717eeeeaa8c5b6e53743b868e27de4e55e9be`; smoltcp remains pinned to
`517222f7318c092d82197e2e68cfccca0f460b09`. The FoA change requests HAL sequence
assignment for generated station data, EAPOL, authentication and association
frames. Previously these sites serialized a zero sequence field and left
assignment disabled. The HAL assigns a number before its retry loop, preserving
that number for the queued frame's retries. See the
[FoA source review](https://github.com/opensensor/FoA/blob/c83717eeeeaa8c5b6e53743b868e27de4e55e9be/tests/STA-SEQUENCES.md).

## Test conditions and outcome

The signed S3 application was flashed only at `0x20000` on September 10, 2026.
Its SHA-256 is
`b2916434570ff8a2f8202f4e7bd6b83ad004c0e6e703db8018bedaea9932ce82`.
The test used the existing secured board, AP and private network configuration.
C3 station testing was paused throughout this S3 run.

The build enables `esp32s3,network-trace,foa/tx-trace` and uses the log filter
`info,smoltcp=trace,embassy_net=debug,foa::tx_queue=trace,foa_sta=info`. The FoA
completion trace records queue/generation, frame length, frame type, protection
flag, sequence and actual endpoint result. It excludes addresses and payload.
The private packet trace separately records the FoA/embassy boundary; raw logs,
credentials and firmware are excluded from this repository.

Every cycle connects, obtains DHCP, accepts twenty host pings with a 512-byte
payload at 0.2-second intervals, then sends twenty 512-byte gateway pings before
disconnecting. The first host ping is counted and there is no explicit ARP
warm-up. All ten cycles ran, but the final gateway-loss assertion failed.

| Result | Count |
| --- | --- |
| Unique host replies | 199/200 |
| Gateway replies | 194/200 |
| Duplicate host receipts, counted separately | 1 |
| Payload/checksum diagnostics | 0 |
| Transmission-exhaustion warnings | 0 |

The earlier `ff26efec` S3 trace baseline was built, signed and preserved but never
flashed. The previous S3 combined-image failure and successful repeat remain in
[the earlier comparison](PENDING-RESPONSES.md#combined-foa-and-smoltcp-queue-validation).
There was no repeat of this corrected trace image.

## Sequence and completion evidence

There are exactly **504 start events and 504 finish events**, all paired by
hardware queue and generation. Every event uses queue 2; generations are 0
through 503. No start/finish pair changes interface, frame length, type or
protection flag. Ordering the completed headers by their paired start events
produces sequence numbers **0 through 503**, with every delta equal to one.
The first assigned zero is valid; later generated frames no longer repeat it.

The trace contains ten authentication requests, ten association requests, ten
deauthentication frames, twenty clear data/EAPOL frames and 454 protected data
frames. Each category participates in the same advancing sequence stream.

| Actual endpoint result | Frames |
| --- | --- |
| `Ok(0)`: success without a software retry | 473 |
| `Ok(1)` | 26 |
| `Ok(2)` | 3 |
| `Ok(3)` | 2 |
| Error | 0 |

This establishes sequence assignment and successful endpoint completion. It
does not capture every physical attempt or its on-air Retry bit, nor prove that
a peer application processed an acknowledged frame.

## Locate the missing replies

Each lost gateway request appears at the IP transmit boundary, followed by
exactly one protected 588-byte frame start and its matching finish before the
one-second response timeout. There are no intervening FoA starts in those
windows. All six finish results are `Ok(0)`; the corresponding gateway replies
never appear at the receive boundary.

| Cycle | ICMP sequence | Queue generation / assigned sequence | MAC result | RX head at timeout |
| --- | --- | --- | --- | --- |
| 3 | 3 | 133 | `Ok(0)` | Empty, incomplete |
| 5 | 10 | 239 | `Ok(0)` | Empty, incomplete |
| 6 | 11 | 291 | `Ok(0)` | Complete, length 472 |
| 7 | 15 | 345 | `Ok(0)` | Empty, incomplete |
| 8 | 1 | 381 | `Ok(0)` | Empty, incomplete |
| 10 | 11 | 493 | `Ok(0)` | Empty, incomplete |

ARP receive traffic continued during the missing-response windows in cycles 8
and 10. The cycle-6 completed descriptor cannot be identified from the captured
metadata; it is not evidence that the missing echo reply was received. All six
snapshots report interrupt status zero. The full register-state summaries and
boundary timestamps are in the JSON evidence.

The missing host reply is cycle 4, ICMP sequence 7. Its request is absent at the
FoA/embassy receive boundary and no corresponding reply reaches transmit.
The one duplicate is cycle 1, sequence 6: the boundary records one request and
one reply, while its associated completion is generation/sequence 13 with
`Ok(1)`. The host receives that reply twice. This associates the duplicate with
a retried transmission, but does not establish the on-air duplicate/Retry-bit
behavior without a monitor capture.

The six missing gateway replies include successful first attempts, so these
losses are not explained by a reported retry exhaustion. The sequence correction
is demonstrated independently of the remaining receive/delivery problem. One
board, one AP and a trace-enabled application do not establish long-duration
reliability or isolate all RF, peer-stack and driver causes.

[Machine-readable evidence](sta-sequence-validation.json) includes exact source
and dependency hashes, every cycle, sequence lists by frame category, paired
completion counts, retry histograms and each lost-packet correlation. The board
was left disconnected at the final assertion; the test was not rerun.
