# C3/S3 transmit-gain validation

Implementation `6b7dc8e390867797cce7a44de1b1eebd49d5b51b` replaces all 11 C3 and 12 S3 live `phy_tx_gain.o` functions. Control is `8ab63be90f75c3f5ff97067ba98ba0e48d0fdf6f` with the identical passive lifetime probe. [Contracts](PHY-TX-GAIN.md); [numeric evidence](phy-tx-gain-validation.json).

## Source and native checks

1,566 C3 and 1,784 S3 cases match production Rust at O0/O2, reaching all 642/712 recorded instructions and all 62/68 conditional edges. S3 includes 90 instructions from two existing Rust dependencies. A deterministic joint sweep adds 1,024 cases per chip at both optimization levels. Nineteen oracle checks, two Rust tests per configuration and all 284 allocation tests pass. Python checks also run under -O. HAL regressions and ESP32/S2 compatibility checks pass. The fixture re-extracts exactly from pinned ELF bytes, including readonly tables and format strings.

All 16 firmware builds have verified source/lock hashes and pass the complete ownership gates. Eight source profiles pass 13,400 native case executions across 100 emitted bodies (92 TX gain bodies and eight instances of the S3 dependencies). Only the unused twelfth internal Wi-Fi generator argument is masked; the compiler may omit its outgoing stack slot. All consumed arguments and observable effects remain checked. The joint sweep exposed an overflow in synthetic host callback output generation; explicit wrapping and a regression test correct the mock. No production firmware semantic correction was needed.

## Allocated vendor PHY

| Chip/profile | Control bytes | Rust bytes | TX gain member | Remaining members |
|---|---:|---:|---:|---:|
| esp32c3/ordinary | 17233 | 15255 | 1980 → 0 | 3 |
| esp32c3/GTK | 17233 | 15255 | 1980 → 0 | 3 |
| esp32s3/ordinary | 15395 | 13434 | 1969 → 0 | 3 |
| esp32s3/GTK | 15387 | 13426 | 1969 → 0 | 3 |

Three vendor members remain: initialization, RX calibration and TX calibration. Earlier replaced members, libpp and the prebuilt formatter remain absent. ROM and vendor-owned state remain dependencies. Counts describe non-string vendor input allocations, not total firmware savings. Every retained input name is preserved. C3 call encodings explain the two-byte increases in bb_init and, in lifetime/RX profiles, rf_init. S3 literal placement explains one four-byte decrease and three four-byte increases. Resolved instructions agree in all eight paired profiles. Sixteen IRAM entry/literal checks pass; runtime callback targets do not imply transitive flash independence.

## Paired boards

All eight lifetime/RX trials complete. Each lifetime trial performs three PHY guard cycles, validates prior probes, checks all TX gain entry addresses and callback bindings, and records table fingerprints. Control and source table fingerprints match across all three cycles on each chip. The added probe is passive. RX trials preserve pending buffers, recover from exhaustion and transmit OFDM.

| Chip | Trial | Router echoes | Gateway echoes | Broadcast | Multicast | GTK rotations |
|---|---|---:|---:|---:|---:|---:|
| esp32c3 | control-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32c3 | source-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32c3 | control-gtk-v1 | 300/300 | 20/20 | 119/120 | 120/120 | 3/3 |
| esp32c3 | source-gtk-v1 | 300/300 | 20/20 | 119/120 | 120/120 | 3/3 |
| esp32c3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | control-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | source-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | control-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 3/3 |
| esp32s3 | source-gtk-v1 | 300/300 | 20/20 | 119/120 | 120/120 | 3/3 |
| esp32s3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |

Every planned trial, including any loss, is retained. No retry-until-pass selection was used. Independent raw-pcap parsing checks echo pairs, group gaps and captured GTK request/G1/G2 intervals. Capture health reports no socket drops, truncation or missing timestamps. Ethernet-side captures cannot locate a loss within the AP, RF path, driver or network stack.

The missed broadcasts are C3 control sequence 22 (732.141 ms after G2 counter 3), C3 Rust sequence 62 (749.824 ms after G2 counter 5), and S3 Rust sequence 41 (193.860 ms after G2 counter 4). Both AP captures contain each packet. Paired multicast packets arrive, and every key rotation completes. This timing context does not identify the loss cause.

## Timing and limits

| Chip | Variant | Console max µs | PHY max µs | TX resume max µs | RX age max µs |
|---|---|---:|---:|---:|---:|
| esp32c3 | control-gtk-v1 | 1791 | 86 | 1330 | 8515 |
| esp32c3 | source-gtk-v1 | 1822 | 88 | 1600 | 8529 |
| esp32s3 | control-gtk-v1 | 4062 | 95 | 2412 | 9367 |
| esp32s3 | source-gtk-v1 | 4276 | 87 | 1752 | 8676 |

These cumulative metrics use one board per chip and one AP. They cannot assign a packet delay or loss to Rust gain programming, prove cycle equivalence or establish RF output-power equivalence. Earlier loss and latency observations remain open. This milestone adds no retry, power or cadence change.

Both boards retain ordinary source applications after restoration trials. Only app slots were flashed, with forced chip/security checks and verified S3 signatures. Owned router workers/files were removed, monitor mode is zero and persistent AP configuration was unchanged. At completion C3 is disconnected; the paired flasher leaves S3 in ROM with its ordinary source app retained.
