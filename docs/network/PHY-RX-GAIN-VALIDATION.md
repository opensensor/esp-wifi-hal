# C3/S3 receive-gain validation

Implementation `55b8d70343bc63115a53e27821c3baeed5dfb04b` replaces all five allocated `phy_rx_gain.o` functions per chip. Control is `d30377444db5a6b34de6897a8eca96917eb59dfc` with the identical passive lifetime probe. [Implementation and contracts](PHY-RX-GAIN.md); [numeric evidence](phy-rx-gain-validation.json).

## Source and native checks

2,604 original-instruction cases per chip match production Rust at O0/O2, reaching all 782 C3 / 709 S3 recorded instructions and all 78/54 conditional edges. A deterministic joint sweep adds 1,024 cases per chip at both optimization levels. Nineteen focused oracle checks and all 262 PHY allocation tests pass normally and under Python -O. C/Rust HAL regressions and ESP32/S2 compatibility checks pass. Exact re-extraction matches the pinned instructions, readonly tables and format strings.

All 16 firmware builds have verified source/lock hashes and pass the complete ownership gates. All eight source profiles pass 20,832 native case executions across 40 emitted bodies. The comparison masks the three unused arguments at the internal set_rx_gain_param boundary; LLVM may leave those registers unset. Every consumed argument, ordered access and modeled effect remains checked. No production firmware correction was needed during comparison.

## Allocated vendor PHY

| Chip/profile | Control bytes | Rust bytes | Receive-gain member | Remaining members |
|---|---:|---:|---:|---:|
| esp32c3/ordinary | 19556 | 17233 | 2323 → 0 | 4 |
| esp32c3/GTK | 19556 | 17233 | 2323 → 0 | 4 |
| esp32s3/ordinary | 17464 | 15395 | 2069 → 0 | 4 |
| esp32s3/GTK | 17456 | 15387 | 2069 → 0 | 4 |

Four vendor members remain: initialization, RX calibration, TX gain and TX calibration. Earlier replaced members, libpp and the prebuilt formatter remain absent. ROM and vendor-owned state remain dependencies. Counts describe non-string vendor input allocations, not total firmware savings. All retained input identifiers and sizes agree across the eight matched profile pairs; link-address relocations are not a byte-identity claim.

## Paired boards

All eight lifetime/RX trials complete. Each lifetime trial performs three PHY guard cycles and validates all prior probes, all five receive-gain entry addresses and post-init gain counts. The new probe is passive and does not initiate calibration or change gain settings. RX trials preserve pending buffers, recover from exhaustion and transmit OFDM.

| Chip | Trial | Router echoes | Gateway echoes | Broadcast | Multicast | GTK rotations |
|---|---|---:|---:|---:|---:|---:|
| esp32c3 | control-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32c3 | source-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32c3 | control-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 3/3 |
| esp32c3 | source-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 3/3 |
| esp32c3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | control-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | source-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | control-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 3/3 |
| esp32s3 | source-gtk-v1 | 298/300 | 20/20 | 120/120 | 120/120 | 3/3 |
| esp32s3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |

Every planned trial, including any packet loss, is retained. No retry-until-pass selection was used. Independent raw-pcap parsing checks echo pairs, group gaps and captured GTK request/G1/G2 intervals. Capture health reports no socket drops, truncation or missing timestamps.

S3 source misses echo sequences 15 and 159. Both requests are present in both AP captures with no matching reply. Echo 15 occurs 6.993 seconds before the first GTK request, so rekey timing alone cannot explain both losses. Echo 159 occurs 1.763 seconds after G2 counter 5. The preceding echo 14 replies after 227.005 ms; neighboring requests otherwise receive replies. These Ethernet-side observations do not locate the losses within the AP, RF path, driver or network stack.

## Timing and limits

| Chip | Variant | Console max µs | PHY max µs | TX resume max µs | RX age max µs |
|---|---|---:|---:|---:|---:|
| esp32c3 | control-gtk-v1 | 1828 | 87 | 1826 | 8525 |
| esp32c3 | source-gtk-v1 | 1990 | 87 | 1472 | 8504 |
| esp32s3 | control-gtk-v1 | 4462 | 95 | 2344 | 10530 |
| esp32s3 | source-gtk-v1 | 4425 | 93 | 5100 | 9172 |

These cumulative observations use one board per chip and one AP. They cannot assign a packet delay or loss to Rust receive-gain programming, prove cycle equivalence, or establish an RF/timing improvement. Earlier packet losses and latency tails remain open. This milestone adds no retry, power or cadence change.

Both boards retain the ordinary source applications after the restoration trials. Only app slots were flashed, with forced chip/security checks and verified S3 signatures. Owned router workers/files were removed, monitor mode is zero and persistent AP configuration was unchanged. At completion C3 is disconnected; the paired flasher leaves S3 in ROM with its ordinary source app retained.
