# EAPOL completion results on C3/S3

FoA `c433109960bc2b346a45da47c2bd3d2cb32690bf` fixes the common EAPOL sender's
handling of a missing TX completion. Previously, `wait_for_completion()`
returning `None` became `Ok(())`. It now becomes `StaError::TxCompletionLost`:
the radio outcome is unknown. Only a reported MAC success returns `Ok(())`.
The existing reported-error mapping to `AckTimeout` is unchanged.

This covers pairwise handshake replies and established-PTK group requests and
replies. It does not introduce another transmission, alter the eight-attempt
MAC policy, reuse a protected frame's packet number, or change key installation.
Adding a public error variant requires downstream exhaustive matches on
`StaError` to handle it.

The queue can legitimately lose a completion when a completed slot is reused
before its waiter runs, or when an active runner is dropped without returning
completion data. Existing production-queue tests exercise both cases. This fix
preserves that queue contract and stops interpreting an unknown outcome as
success.

## Regression evidence

The host harness compiles the actual production serializer and EAPOL senders,
with a mock MAC endpoint. The new test failed on the old sender:
`sender 0, completion None: Ok(())` instead of `Err(TxCompletionLost)`.
It then passed with the fix, checking all nine combinations of M4, G2 and group
request with successful, failed or missing completion. Assertions check one
submission, clear M4 without PTK PN consumption, and protected G2/request with
exactly one consumed PN. Missing PTK still prevents group transmission.

All 31 station replay/routing tests pass in debug and release. Queue tests pass
with the normal pool (15), reduced pool in release (15), and TX tracing (17).
FoA CI also runs the existing station-response regressions. Native ordinary
and GTK builds pass on C3 and S3; ordinary ESP32/S2 compatibility checks pass.

```sh
# In the OpenSensor FoA checkout:
sh tests/run-sta-replay.sh
sh tests/run-sta-replay.sh --release
sh tests/run-tx-queue.sh
sh tests/run-tx-queue.sh --release --features small-pool
sh tests/run-tx-queue.sh --features tx-trace
```

## Device comparison

The [numeric report](eapol-tx-completion-validation.json) records the compiled
sources, ELF/map/firmware hashes, capture health, payload-matched echoes and
AP-observed exchanges. The control uses FoA `2143118`; the source uses `c433109`.
Both use HAL `83eb8c2`'s completed PHY replacements and identical probe logging
from HAL implementation `93edf9b`. Only the two FoA lockfile entries change.
Sys remains `73add8985cec3b7582e6df80a4273022deb844b0`.

Both run at 80 MHz with quiet timing logs. Ordinary trials use two connections
with ten-second traffic windows. GTK trials use one 90-second window, three
station-initiated requests, 300 router echoes, 20 gateway echoes, 120 broadcast
and 120 multicast datagrams. Echo payloads are 512 bytes; group payloads are
128 bytes. See the [GTK exercise](GTK-REKEY.md#reproduce-the-mixed-traffic-exercise)
for build flags and router tooling. Requests remain explicitly opt-in.

| Chip | Trial | Router echoes | Gateway echoes | Broadcast | Multicast | Median / maximum router RTT (ms) |
| --- | --- | --- | --- | --- | --- | --- |
| esp32c3 | control-normal-v2 | 40/40 | 40/40 | — | — | 3.515 / 26.873 |
| esp32c3 | source-normal-v2 | 40/40 | 40/40 | — | — | 4.960 / 54.021 |
| esp32c3 | control-gtk-v2 | 300/300 | 20/20 | 119/120 | 120/120 | 4.112 / 74.348 |
| esp32c3 | source-gtk-v2 | 300/300 | 20/20 | 120/120 | 120/120 | 4.097 / 107.999 |
| esp32c3 | source-restored-v2 | 40/40 | 40/40 | — | — | 13.611 / 31.086 |
| esp32s3 | control-normal-v2 | 40/40 | 40/40 | — | — | 2.522 / 32.376 |
| esp32s3 | source-normal-v2 | 40/40 | 40/40 | — | — | 2.943 / 41.223 |
| esp32s3 | control-gtk-v2 | 300/300 | 20/20 | 120/120 | 120/120 | 3.133 / 46.897 |
| esp32s3 | source-gtk-v2 | 300/300 | 20/20 | 120/120 | 120/120 | 4.492 / 81.578 |
| esp32s3 | source-restored-v2 | 40/40 | 40/40 | — | — | 4.602 / 47.805 |

All 12 station requests returned `Ok(())`, each with one retained event-8
MAC-success record and no overwritten window events. The AP `eth10` capture
contains all three matching request/G1/G2 exchanges in every trial, with no
same-key retries. Both `eth10` and `br0` observe the station requests and G2
replies; AP-originated EAPOL is visible only on `eth10`. Capture counters report
no drops or truncation.

The esp32c3 control-gtk-v2 trial missed broadcast
sequence 22, present in both AP captures: 704.237 ms
after the preceding completed G2. The cause remains unresolved.

After capture, both boards were restored to the tested ordinary source
application and passed two more reconnect cycles each. These images do not
request GTK rotations on reset. Only the existing app slots were written;
the S3 image was signed and verified with its existing key.


All eight station/GTK link audits retain 15 allocated vendor PHY members,
no I2C/PBUS/sensor member allocation, and no allocated `libpp.a`. The PHY
implementation, callback behavior and other dependency pins are unchanged.

## Interpreting the probe

`stage=gtk_request` now records the actual `Result` and monotonic start/end
microseconds. `stage=gtk_request_events` reports the number of flight-recorder
events during the request and any overwritten records. `stage=eapol_tx_window`
prints only event-8 metadata: 0 is MAC success, 1 MAC error, and 2 missing
completion. Its timestamp is relative to the connection's recorder reset;
request start/end timestamps use the monotonic clock's epoch. The event window
may include a concurrent G2 and does not uniquely identify every transmission.
Logging occurs after the request, outside the MAC interrupt path.

A MAC success still does not establish AP acceptance or a completed GTK
rotation: compare the station's result with captured requests and matching
G1/G2 counters. The host regression deliberately supplies missing completions;
these hardware trials do not inject queue failures. Their successful normal
paths do not prove that the missing-completion condition can never occur.

The [earlier I2C trial](PHY-I2C-FLASH-VALIDATION.md) that reported a successful
third request absent from both AP captures remains unexplained. Its per-request
completion discriminant was not retained, so this correctness fix is not proof
of that loss's cause. Short sequential trials also do not resolve the historical
intermittent echo/broadcast losses or establish indefinite reliability.
