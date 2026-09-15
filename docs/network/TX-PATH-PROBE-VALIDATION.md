# Bounded TX probe: C3/S3 device comparison

Firmware HAL `6af3dd0f4aa058b0a521d8bd92d303a86c196257`, FoA `dd4db9de3f427db53965e48c731eec786b645421`, sys `73add8985cec3b7582e6df80a4273022deb844b0`. The lockfile changes only the FoA/FoA-STA commit; other dependencies and PHY sources stay fixed.

The optional probe now records each owned gateway request from station MSDU handoff through software queue insertion, pickup and the real HAL completion. Its 64-entry store occupies 5,184 bytes on either chip. There is no per-packet formatting in the TX path. The example prints bounded records after each gateway batch, before its existing loss assertion. Ordinary builds have no probe STATE symbol.

All ten fixed attempts completed: **400/400 gateway replies and 400/400 router echoes**. Each chip ran baseline, probe, probe, baseline; then both ordinary images were restored. Each attempt used two reconnect cycles, twenty router echoes per cycle during the ten-second host window, followed by twenty gateway requests. No GTK rotation or network/timing trace feature was selected. The ordinary logger and default ESP-HAL clock configuration remain unchanged.

The four instrumented attempts produced **160 complete, distinct submission records**, with zero capacity, identity, ordering or scope-change errors. Every request is present in both independent AP Ethernet captures with one matching reply. Capture writers report no drops, truncation or missing timestamps. A successful software result alone is not treated as packet-delivery evidence.

145 requests succeeded with zero reported driver retries, 12 with one retry and 3 with two. C3 accounts for seven single-retry requests; S3 accounts for five single-retry and three double-retry requests. No exhausted operation occurred in this comparison. The previous [C3 restoration failure](PHY-TX-DETECTOR-VALIDATION.md) remains valid evidence and has not been reproduced or fixed.

## Measured intervals

C3 queue waiting (insertion to pickup) stayed at or below 244 us; S3 at or below 155 us. The largest pickup-to-HAL-completion interval was 98,456 us: S3 probe B, cycle 2, sequence 12, which succeeded after two driver retries. This interval includes setup, scheduling, hardware waits and the existing power-control work; it does not isolate on-air time or identify a specific cause. The probe has no low-level attempt-start hook.

Router-originated echo RTTs, separate from the outgoing gateway probe intervals:

| Chip | Trial | Median ms | p95 ms | Maximum ms |
|---|---|---:|---:|---:|
| esp32c3 | baseline-a | 5.198 | 14.653 | 23.184 |
| esp32c3 | probe-a | 4.104 | 21.618 | 33.231 |
| esp32c3 | probe-b | 11.176 | 37.023 | 50.640 |
| esp32c3 | baseline-b | 5.769 | 46.227 | 51.631 |
| esp32s3 | baseline-a | 4.322 | 26.845 | 105.769 |
| esp32s3 | probe-a | 4.873 | 38.649 | 58.119 |
| esp32s3 | probe-b | 7.178 | 85.128 | 148.498 |
| esp32s3 | baseline-b | 3.225 | 40.211 | 86.360 |
| esp32s3 | baseline-restored | 4.517 | 28.450 | 35.660 |
| esp32c3 | baseline-restored | 6.361 | 40.938 | 111.599 |

RTT tails remain in both variants. These small alternating samples do not establish a latency improvement, absence of observer overhead, or a lower loss rate. They validate the observation path needed for the next failure.

## Software and source checks

The actual FoA queue, buffer manager, recorder, synchronization and clock pass host tests with default and three-buffer pools, debug/release arithmetic and existing TX tracing. The probe suite has 24 tests, including a cancelled radio-wait future retaining an incomplete record and recovering its buffer. The serial report parser passes five tests in normal and optimized Python, preserving failures and rejecting malformed or contradictory records.

All four application builds pass the composed source-ownership gates. The remaining non-string vendor PHY allocation stays 4,852 bytes on C3 and 3,663 bytes on S3, with sixteen TX functions per chip. The whole RX calibration member remains absent. This milestone replaces no additional PHY functions.

Only application slots were flashed, with forced chip/security checks and verified S3 signatures. Owned router tools and workers were removed; monitor mode is zero and persistent AP configuration is unchanged. C3 completed and disconnected both restoration cycles; the paired flasher leaves S3 held in ROM with its ordinary image retained.

## Reproduce and interpret

Add `tx-probe` to the selected chip features for `sta_smoke`; it enables `foa-smoke`, `foa/tx-probe` and `foa_sta/tx-probe`. Retain the baseline radio and logger settings. The application arms only its owned ICMP batch (identifier 0x5353, sequences 1..20, 512-byte 0x5a payload), disarms after the batch, and prints each cycle once. No addresses, keys, packet numbers or payloads appear in the records. Entries are copied individually, so a still-pending operation can finish after its snapshot. Capacity exhaustion is reported and never overwrites earlier records.

See [numerical results and provenance](tx-path-probe-validation.json), [strict serial parser](tools/tx_probe_report.py), and [FoA recorder contract](https://github.com/opensensor/FoA/blob/dd4db9de3f427db53965e48c731eec786b645421/tests/TX-PROBE.md). Raw captures and serial logs remain private.

The next timing experiment should distinguish per-attempt setup/start, interrupt result, task resumption and PHY power-control time inside the long completion interval. Keep ACK/retry and crypto policy fixed. The tested TX IQ prototype remains queued for the next PHY replacement milestone.
