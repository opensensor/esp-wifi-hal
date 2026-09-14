# RX-control validation — C3 and S3

Implementation `800b2420161d82fa01ea456f95cf607f16de3c53`; control `6514fac29446e4ad7062fa7bb6f31389f384934b` with the identical passive lifetime probe. The tightened allocation auditor is `78a2a5e29853dffe329a8a5c81d78c903328f490`.

Four public receive controls per chip are Rust, with the C3 compiler-split reset tail inlined. The remaining 10 C3 / 12 S3 RX calibration bodies, TX calibration and ROM are retained. FoA/sys pins are unchanged.

## Software and linked images

- All 16 immutable build source/lock records and composed allocation gates pass.
- 754 C3 / 712 S3 original-instruction cases pass at O0/O2: all 178/173 instructions and 14/12 conditional edges covered.
- Nine oracle tests and nine new allocation tests pass normal and optimized Python. All 312 allocation tests, earlier host regressions and ESP32/S2 compatibility checks pass.
- Eight emitted source profiles pass 5,696 native case executions across 32 bodies. Actual instructions, literals, MMIO/state order, callback generations and consumed private input bytes are checked.
- Every retained calibration input has the same name and size in each control/source pair. This is not a byte-identity claim across relocations. Earlier IRAM entry/state ownership checks remain enforced.

| Chip/profile | Vendor PHY before → after | RX calibration before → after |
|---|---:|---:|
| esp32c3 ordinary | 10442 → 9928 B | 5414 → 4900 B |
| esp32c3 GTK | 10442 → 9928 B | 5414 → 4900 B |
| esp32s3 ordinary | 9273 → 8751 B | 5459 → 4937 B |
| esp32s3 GTK | 9265 → 8743 B | 5451 → 4929 B |

## Paired device trials

All eight lifetime/RX trials complete: three PHY lifetimes, callback bindings, beacon reception, pending buffers, exhaustion recovery and transmission checks. Configuration and TX-gain fingerprints are reported for both sides. The lifetime probe supplies deliberately invalid input calibration data; all three subsequent PHY cycles complete and receive beacons.

| Chip | Trial | Router echoes | Gateway echoes | Broadcast | Multicast | GTK rotations |
|---|---|---:|---:|---:|---:|---:|
| esp32c3 | control-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32c3 | source-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32c3 | control-gtk-v1 | 300/300 | 20/20 | 120 | 120 | 3 |
| esp32c3 | source-gtk-v1 | 300/300 | 20/20 | 120 | 120 | 3 |
| esp32c3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | control-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | source-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | control-gtk-v1 | 300/300 | 20/20 | 119 | 120 | 3 |
| esp32s3 | source-gtk-v1 | 300/300 | 20/20 | 118 | 120 | 3 |
| esp32s3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |

Across all 18 trials including restoration: router 1440/1440, gateway 320/320, broadcast 477/480, multicast 480/480, GTK rotations 12/12. Every completed trial is retained; no retry-until-pass selection.

Retained loss — esp32s3 control-gtk-v1: router sequences []; group gaps {'broadcast': [61], 'multicast': []}.

Retained loss — esp32s3 source-gtk-v1: router sequences []; group gaps {'broadcast': [42, 62], 'multicast': []}.

esp32s3 control-gtk-v1 group 0 sequence 61: present at eth10/br0=True/True, 153.988 ms after the preceding G2. Its paired group frame was sent 0.086 ms later. Timing alone does not establish cause.

esp32s3 source-gtk-v1 group 0 sequence 42: present at eth10/br0=True/True, 581.08 ms after the preceding G2. Its paired group frame was sent 0.081 ms later. Timing alone does not establish cause.

esp32s3 source-gtk-v1 group 0 sequence 62: present at eth10/br0=True/True, 587.833 ms after the preceding G2. Its paired group frame was sent 0.097 ms later. Timing alone does not establish cause.

Independent raw-pcap review checks echoes, group delivery, EAPOL order and captured request/response intervals. Capture health is included in the numerical report. AP Ethernet captures do not locate a loss within RF, MAC, driver, stack or response transmission.

## Timing and limits

- esp32c3: control/source maximum PHY 87/88 µs; TX resume 1580/1740 µs.
- esp32s3: control/source maximum PHY 87/95 µs; TX resume 103/2486 µs.

Quiet logging and 80 MHz CPU settings are matched. Cumulative timing includes preemption and cannot identify individual packet causes. Per-frame GTK INFO logging remains an unresolved measurement interference concern. One board per chip, one AP and room-temperature tests do not establish calibrated RF, analog, cycle or long-duration reliability equivalence.

Ordinary source applications are restored on both boards. App slots only; forced chip/security checks and verified S3 signatures. Owned router workers/files removed, monitor disabled, persistent AP configuration unchanged. C3 completed and disconnected; paired flashing leaves S3 held in ROM with its ordinary source application retained.

See [numerical evidence](phy-rx-controls-validation.json), [implementation notes](PHY-RX-CONTROLS.md) and [oracle](tests/phy-rx-controls-oracle/README.md).
