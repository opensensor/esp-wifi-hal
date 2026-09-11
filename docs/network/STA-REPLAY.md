# Reject a repeated protected frame before network delivery

The examples pin OpenSensor FoA
[`39f44767`](https://github.com/opensensor/FoA/commit/39f44767178462e0c5e02aa8a8bd220c8cfd1bd3).
Its station receive path previously accepted a CCMP packet number equal to the
last accepted number. The comparison now requires a strictly greater value.
The [HAL Retry correction](MAC-RETRIES.md), generated sequence assignment and
smoltcp pending-response correction remain enabled.

Seven host tests compile the actual FoA replay-check and routing methods with
the real frame parser, replacing the crypto-state container and final network
buffer sink. All pass in debug and release; five fail against the earlier
source. The duplicate-delivery test measures one network delivery after the
correction versus two before it. Independent review reran the seven
tests. FoA's replay and TX-queue CI both passed at the pinned revision.

The production change is one comparison. Pairwise and group counters remain
separate; fresh receive counters start at zero and accept the first PN of one.
FoA checks once per frame before software subframe iteration. The change adds
no logging and does not change transmit policy or key installation. See
[the exact host tests and protocol scope](https://github.com/opensensor/FoA/blob/39f44767178462e0c5e02aa8a8bd220c8cfd1bd3/tests/STA-REPLAY.md),
including existing per-TID, group-key and parser limitations.

## Device comparison

The dedicated C3 and S3 checks use ten WPA2/DHCP/reconnect cycles, twenty
512-byte host pings followed by twenty gateway pings per cycle, and the same
packet/MAC trace profile as the preceding Retry-only runs. Only the FoA
receive comparison changes. Hardware runs are serialized: the other station
remains disconnected. Each first attempt is retained, including failures.

| Chip | Unique host replies | Gateway replies | Extra host replies | Application result |
| --- | --- | --- | --- | --- |
| C3 | 200/200 | 200/200 | 0 | Completed ten cycles |
| S3 | 200/200 | 199/200 | 0 | Ten cycles, final gateway assertion failed |

C3 recorded 503 paired starts/completions with assigned sequences 0 through
502: 471 `Ok(0)`, 24 `Ok(1)`, five `Ok(2)`, one `Ok(3)` and two `Ok(4)`.
Every host request and reply appeared once at its corresponding IP boundary.
There were no exhausted-transmission warnings; nine pending neighbor responses
were queued and dispatched. The host capture recorded zero socket drops.
All first pings count. Image SHA-256:
`949832ab95d704153780ac1c2da88fb0145aca864d9581513796660cb32c7cac`.
See [C3 evidence](sta-replay-validation-c3.json).

S3 recorded 507 paired successful completions, advancing through sequences
0 through 506, and zero observed duplicates. Its missing gateway reply is
cycle 1 sequence 2: generation 30 completed `Ok(0)`, but no reply reached the
IP receive boundary. The timeout RX head was empty and interrupt status zero.
See [the complete S3 report](../esp32s3/RX-PN.md).

These traces observe IP boundaries and final MAC completions, but do not
record incoming CCMP packet numbers or on-air Retry flags. They cannot prove
that equal packet numbers caused a historical duplicate. The host regression
establishes the acceptance defect; device tests establish the recorded traffic
outcomes. Remaining losses must be diagnosed independently.
Each final device log also contains one generic `Dropping MSDU` message. Its
reason is not recorded, so it is not evidence of a specific replay rejection
and the reports do not claim that every received frame reached the network.
The clean C3 run does not erase the preceding CTS failures, and these bounded
tests do not establish a statistical reduction in loss or duplicates.
