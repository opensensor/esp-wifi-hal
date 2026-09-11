# Queued authentication responses during association

The station could fail reconnect with
`AssociationFailure(TdlsRejectedAlternativeProvided)` even when no association
rejection was sent. An authentication response queued behind the first successful
response survived the transition to association. The `ieee80211` 0.5.9 typed
management parser checks the management family but not the requested subtype:
authentication's body fields `(algorithm=0, transaction=2, status=0)` were read
as association `(capabilities=0, status=2, AID=0)`.

FoA now checks each dequeued authentication/association response against the
current scoped operation before handing it to the typed parser. It releases a
stale buffer and waits for the correct response under the original timeout.
Matching rejection responses retain their original behavior. The change does
not flush queues, change retry timing, or alter background deauthentication or
the EAPOL handshake's existing parsing loop.

## Reproduction and device evidence

Nine host tests compile the production router, operation classifier, state
tracker and response helper with the actual parser. They reproduce status 2 from
two successful authentication responses followed by a successful association
response. With the fix, the stale response is released and the genuine association
response is returned. Other cases retain real rejection statuses, background
traffic and EAPOL classifier compatibility. A mock-clock check discards a full
backlog at 9 ms into a 10 ms timeout and still expires at the original deadline.
Debug and release tests pass; independent review found no blocking issue.

The corrected S3 device trace records this event during cycle 4:

```text
stage=sta_stale_frame us=61592244 rx_timestamp=61561323 operation=associating frame_type=Some(Management(Authentication))
```

Association and traffic then succeeded, and all ten reconnect cycles completed.
This directly establishes that the stale authentication-frame path occurs on
the board and that the new check recovers from it. It does not retroactively
prove the precise contents of an unrecorded frame in either earlier failing run.
The monotonic handling time and raw 32-bit RX timestamp are different clock
domains; their difference is not a queue-age measurement.

## Controlled comparisons

Each station image attempts ten reconnect cycles with twenty 512-byte host pings
and twenty 512-byte gateway pings per cycle, including the first ping without ARP
warming. Exactly one test station is active at a time. Rust comparisons use the
same trace profile; source-clock verification adds one initial MAC-register
readout. The C control is the unchanged signed image from the
[earlier reviewed C comparison](../esp32s3/C-RUST-CONTROL.md), with its own logging
and full-init/deinit test loop. All observations, including failures, are retained.

| Image | Traffic cycles | Host unique replies | Gateway replies | Result |
| --- | ---: | ---: | ---: | --- |
| S3 connection diagnostics, fixed clock constant | 4 | 80/80 | 78/80 | Association status 2 in cycle 5 |
| S3 diagnostics, measured clock | 3 | 60/60 | 59/60 | Association status 2 in cycle 4 |
| S3 reviewed C control | 10 | 200/200 | 200/200 | Complete |
| S3 measured clock and response revalidation | 10 | 200/200 | 196/200 | Final gateway assertion failed |
| C3 response revalidation | 9 | 180/180 | 180/180 | Connection timeout during cycle 10 handshake |
| C3 earlier diagnostic image, subsequent control | 10 | 200/200 | 200/200 | Complete |

No host duplicates were recorded in these S3 runs. The host captures report zero
socket drops. The two status 2 failures had no recorded deauthentication events;
the corrected S3 run recorded only user-requested link teardown. There were no
pending-response evictions in these Rust runs. These individual observations do
not establish equal loss rates or a general packet-loss fix.

The corrected S3 run still lost gateway cycle 3/sequence 20, cycle 5/sequences 8 and 17,
and cycle 9/sequence 20. All 506 TX starts have matching successful MAC completions;
there are no unmatched generations or exhausted-TX warnings. A successful MAC
completion does not prove AP forwarding or delivery of the reply. Host captures
provide an Ethernet view, not over-the-air evidence. The host has no spare radio
currently prepared for a 2.4-GHz monitor capture; its active network was unchanged.

Those four timeouts follow queue 2 generations 149, 239, 248 and 453 respectively.
Each is a 588-byte protected transmission with `Ok(0)`, no matching RX echo in
that cycle, and an empty incomplete RX head (`flags=0x80000640`). The completed
TX records contain no MAC error that explains these losses.

The corrected C3 run completed nine clean traffic cycles and reached the WPA2
handshake in cycle 10 before the connection timeout. Authentication, association
and one unprotected EAPOL transmission had successful MAC completions. A
deauthentication frame with parsed reason 15 arrived during the handshake but
could not be queued. Its address-match booleans default to false because no
established connection exists at that point; they do not identify the sender
or establish causality. There were no stale-response events in this run. The
response correction does not change EAPOL processing or background queue ownership.
The earlier C3 diagnostic image was then run as a control and completed all ten
cycles with 200/200 replies in both directions, without a stale-response or
deauthentication event. The corrected C3 run remains a failed validation
observation; this single control does not isolate the timeout's cause.

The S3 [slow-clock correction](../esp32s3/SLOW-CLOCK.md) independently programmed
the MAC field from measured RTC data and passed the formatter ABI/RX recovery
and PHY shutdown/wakeup probes. Those results do not explain the remaining loss.

The [sanitized report](clock-connection-validation.json) records exact image,
ELF, map, lockfile, serial and capture hashes, source revisions, all cycle totals
and failures. Early builds use a local FoA checkout at the recorded commit;
the equivalent production revision is pinned in the final examples. No firmware,
credentials, keys, frame payloads or raw network logs are published.
Both final Git-pin application crossbuilds pass, and their checked-out FoA source
matches the reviewed local production source. They are recorded separately as
build-only images; the hardware results refer to the exact earlier image hashes.

## Remaining boundaries

The host reproduction also demonstrates that background management frames can
survive a reconnect, retaining RX buffers. That separate behavior is not fixed
by response-subtype revalidation. A deauthentication received after a new
authentication starts might be a genuine rejection; indiscriminate flushing when
entering Connected could hide it. A separate fresh-attempt cleanup experiment
has not been integrated or device validated.

Further packet-loss investigation needs evidence about the AP-facing delivery
and RX path, while keeping the current source-clock and response-parser
corrections. Increasing the response queue or changing RF tracking based only on
these ping counts would not identify the missing frame's path.

## Reproduce

Run `sh tests/run-stale-deauth.sh` and the same command with `--release` in
OpenSensor FoA. The HAL examples enable `foa_sta/connection-trace` through their
optional `network-trace` feature. Build `sta_smoke` for C3 or S3 with
`network-trace,foa/tx-trace`, ten configured cycles and private build-time
credentials. Keep this log filter when comparing the recorded Rust runs:

```text
info,embassy_net=trace,smoltcp=trace,foa=debug,foa::tx_queue=trace,foa_sta=info
```

This exposes compact connection events without enabling handshake debug logs.
The hardware scripts update only the boards' existing application slots; S3
images use the existing signing key. No bootloader, partition or eFuse changes
are part of this validation.
