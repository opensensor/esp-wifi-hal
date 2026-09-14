# C3/S3 register-programming validation

Implementation `aaf086d32976146b42b2c6586b020cb6a9f5c407` replaces the 16 allocated `phy_reg.o` functions per chip. Control is `f93fc38a7f83645b66086cbb579b092d801a92e0` with the identical passive lifetime probe. [Implementation and contracts](PHY-REG.md); [numeric evidence](phy-reg-validation.json).

## Source and native checks

4,500 original-instruction cases per chip match production Rust at O0/O2, reaching all 619 C3 / 774 S3 recorded instructions and both edges of all 21 conditionals per chip. A deterministic joint mutation sweep adds 1,024 cases per chip at both optimization levels. Twenty focused oracle checks and all 249 PHY allocation tests pass normally and under Python -O. C/Rust HAL regressions and ESP32/S2 compatibility checks pass. Exact re-extraction matches the pinned fixture.

All 16 firmware builds have verified source/lock hashes and pass the complete chain of ownership gates. All eight source profiles pass 36,000 native case executions across 128 emitted bodies. Nine entries per chip and their literal pools reside in IRAM. ROM delays resolve correctly. No firmware correction was needed during host/native comparison.

## Allocated vendor PHY

| Chip/profile | Control bytes | Rust bytes | Register member | Remaining members |
|---|---:|---:|---:|---:|
| esp32c3/ordinary | 22206 | 19556 | 2664 → 0 | 5 |
| esp32c3/GTK | 22206 | 19556 | 2664 → 0 | 5 |
| esp32s3/ordinary | 21419 | 17464 | 3947 → 0 | 5 |
| esp32s3/GTK | 21411 | 17456 | 3947 → 0 | 5 |

Five vendor members remain: initialization, RX gain, RX calibration, TX gain and TX calibration. Earlier replaced members, libpp and the prebuilt formatter remain absent. ROM and vendor-owned state remain dependencies. These counts describe non-string vendor input allocations, not total firmware savings.

C3 retained wakeup grows 2 bytes, rxiq_cover_mg_mp 8 bytes and rfcal_rxiq 4 bytes as seven compressed calls widen. S3 rf_init and set_rx_gain_param each shrink 4 bytes through literal-pool changes. Resolved instructions, branch destinations and referenced symbols/data agree for those retained functions; other retained input identities and sizes agree.

## Paired boards

All eight lifetime/RX trials complete. Each lifetime trial performs three complete PHY guard cycles and validates all prior probes, all 16 register entry addresses, six parameter words per cycle and the raw I2C callback slot. The added probe is passive; it does not initiate tone, IQ, AGC or RF switching. RX trials preserve pending buffers, recover from exhaustion and transmit OFDM.

| Chip | Trial | Router echoes | Gateway echoes | Broadcast | Multicast | GTK rotations |
|---|---|---:|---:|---:|---:|---:|
| esp32c3 | control-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32c3 | source-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32c3 | control-gtk-v1 | 299/300 | 20/20 | 120/120 | 120/120 | 3/3 |
| esp32c3 | source-gtk-v1 | 300/300 | 20/20 | 119/120 | 120/120 | 3/3 |
| esp32c3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | control-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | source-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | control-gtk-v1 | 300/300 | 20/20 | 119/120 | 120/120 | 3/3 |
| esp32s3 | source-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 3/3 |
| esp32s3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |

Every planned trial, including any packet loss, is retained in the numeric evidence. No retry-until-pass selection was used. Independent raw-pcap parsing checks echo pairs, group sequence gaps and each captured GTK request/G1/G2 interval. Capture health has no socket drops, truncated records or missing timestamps.

C3 control misses echo 199: both AP captures contain its request without a matching reply, 9.763 seconds after G2 counter 5. esp32c3 source-gtk-v1 misses broadcast 117, present in both AP captures 28.187 seconds after the last completed G2. esp32s3 control-gtk-v1 misses broadcast 21, present in both AP captures 0.230 seconds after the last completed G2. All captured GTK intervals complete without a same-key retry. These observations locate the gaps in time, but do not identify which RF, MAC, driver or stack step lost each packet.

## Timing and limits

| Chip | Variant | Console max µs | PHY max µs | TX resume max µs | RX age max µs |
|---|---|---:|---:|---:|---:|
| esp32c3 | control-gtk-v1 | 1892 | 79 | 1295 | 8420 |
| esp32c3 | source-gtk-v1 | 1865 | 84 | 1624 | 8508 |
| esp32s3 | control-gtk-v1 | 4169 | 98 | 2600 | 8406 |
| esp32s3 | source-gtk-v1 | 3931 | 94 | 5682 | 8390 |

These are cumulative observations from one board per chip and one AP; traffic workloads may differ. They cannot assign a particular packet delay or loss to Rust register programming, prove cycle equivalence, or establish an RF/timing improvement. Earlier packet losses and latency tails remain open. This milestone supplies no retry, power or cadence change.

Both boards retain the ordinary source applications after the restoration trials. Only app slots were flashed, using forced chip/security checks and verified S3 signatures. Owned router workers/files were removed, monitor mode is zero and persistent AP configuration was unchanged. At completion C3 is disconnected; the paired flasher leaves S3 in ROM with its ordinary source app retained.
