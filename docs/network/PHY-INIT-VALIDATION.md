# C3/S3 initialization validation

Implementation `17e572a9c92ec0ead4681fa6757c69c40e856e85` replaces the complete live `phy_init.o` member: 15 C3 and 16 S3 functions and their state. Control is `29178aeb8aa9572ef00a8e6dc201cba69111e81b` with the identical passive lifetime probe. [Contracts](PHY-INIT.md); [numeric evidence](phy-init-validation.json).

## Source and native checks

1,600 C3 and 1,675 S3 cases match production Rust at O0/O2, reaching all 1,178/1,075 recorded instructions and both outcomes of all 110/92 conditional edges. Cases include nested initialization/RF/BB calls and a fixed-seed joint sweep. Twenty-two focused oracle checks and all 303 allocation tests pass, including Python -O. The earlier host regressions and ESP32/S2 compatibility checks pass. The fixture re-extracts exactly from the pinned ELF bytes.

All 16 firmware builds have verified source/lock hashes and pass the complete ownership gates. Eight source profiles pass 13,100 native case executions across 124 emitted bodies. Only the originally unused initialization-pointer argument of the internal checksum helper is masked. Private libc initialization has memory-only effects; consumed buffer bytes remain checked. Mocked local returns respect the ranges available to LLVM. The initial S3 wakeup draft required a correction to the second I2C write's parameter/slot read order before immutable builds or hardware tests.

## Allocated vendor PHY

| Chip/profile | Control bytes | Rust bytes | Initialization member | Remaining members |
|---|---:|---:|---:|---:|
| esp32c3/ordinary | 15255 | 10442 | 4813 → 0 | 2 |
| esp32c3/GTK | 15255 | 10442 | 4813 → 0 | 2 |
| esp32s3/ordinary | 13434 | 9273 | 4165 → 0 | 2 |
| esp32s3/GTK | 13426 | 9265 | 4165 → 0 | 2 |

RX calibration and TX calibration remain as vendor members. Rust now owns the original 848/740-byte parameter state, the 42-byte control storage, the callback-table pointer and the C3 version byte. Earlier replaced members, libpp and the prebuilt formatter remain absent. ROM and calibration remain dependencies. Counts describe non-string vendor input allocations, not total firmware savings.

Every retained input name is preserved. C3 retained input sizes are unchanged. The S3 txiq_cal_init input grows by four bytes in each paired profile; byte-checked resolved instructions match, accounting for the change through literal placement. Sixteen wakeup/close IRAM entry/literal checks pass. These checks do not establish transitive flash independence.

## Paired boards

All eight lifetime/RX trials complete. Each lifetime trial performs three PHY guard cycles, validates prior probes, checks every initialization entry address and the actual state bindings, and records configuration fingerprints. The added probe reads state without invoking initialization again. RX trials preserve pending buffers, recover from exhaustion and transmit OFDM.

Initialization configuration, esp32c3: control/source fingerprints match across the three cycles.
Initialization configuration, esp32s3: control/source fingerprints match across the three cycles.
TX gain tables, esp32c3: control/source fingerprints match across the three cycles.
TX gain tables, esp32s3: control/source fingerprints match across the three cycles.

| Chip | Trial | Router echoes | Gateway echoes | Broadcast | Multicast | GTK rotations |
|---|---|---:|---:|---:|---:|---:|
| esp32c3 | control-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32c3 | source-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32c3 | control-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 3/3 |
| esp32c3 | source-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 3/3 |
| esp32c3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | control-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | source-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | control-gtk-v1 | 298/300 | 20/20 | 120/120 | 120/120 | 3/3 |
| esp32s3 | source-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 3/3 |
| esp32s3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |

Every planned trial, including any loss, is retained. No retry-until-pass selection was used. Independent raw-pcap parsing checks echo pairs, group gaps and captured GTK request/G1/G2 intervals. Capture health reports no socket drops, truncation or missing timestamps. Ethernet-side captures cannot locate a loss within the AP, RF path, driver or network stack.

Recorded loss: esp32s3 control-gtk-v1, router 298/300, gateway 20/20, group gaps `{'broadcast': [], 'multicast': []}`.

Both AP-side captures contain the missing S3 control echo requests (sequences 130 and 174), with no matching replies. Adjacent echoes succeed. The nearest captured key-exchange frames are more than four seconds away; that temporal separation does not locate or explain the losses.

The first local neighbor test build stopped because Rust 1.90 did not meet the pinned dependency’s Rust 1.91 requirement. An isolated 1.91 toolchain completed the affected Cargo tests. The capture tests used the existing Python environment with pyserial 3.5 after the system Python rejected global package installation. These environment failures remain recorded; firmware source and dependency pins did not change.

## Timing and limits

| Chip | Variant | Console max µs | PHY max µs | TX resume max µs | RX age max µs |
|---|---|---:|---:|---:|---:|
| esp32c3 | control-gtk-v1 | 1837 | 87 | 1471 | 8543 |
| esp32c3 | source-gtk-v1 | 1923 | 82 | 1340 | 8529 |
| esp32s3 | control-gtk-v1 | 4433 | 96 | 1541 | 8423 |
| esp32s3 | source-gtk-v1 | 4397 | 91 | 1948 | 8454 |

These cumulative metrics use one board per chip and one AP. They cannot assign a packet delay or loss to Rust initialization, prove cycle equivalence or establish RF calibration equivalence. Earlier loss and latency observations remain open. This milestone adds no retry, power or cadence change.

Both boards retain ordinary source applications after restoration trials. Only app slots were flashed, with forced chip/security checks and verified S3 signatures. Owned router workers/files were removed, monitor mode is zero and persistent AP configuration was unchanged. At completion C3 is disconnected; the paired flasher leaves S3 in ROM with its ordinary source app retained.
