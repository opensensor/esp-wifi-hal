# RX-IQ validation — C3 and S3

Implementation `c178cf90b1bc3aa67174a7003cd618994e1e3994`; control `ccddeb606688a77f599480ee21793e8175d2db0a` with the identical passive lifetime probe. The tightened allocation auditor is `c178cf90b1bc3aa67174a7003cd618994e1e3994`.

Two IQ conversion/correction routines per chip are Rust. The remaining 8 C3 / 10 S3 RX calibration bodies, TX calibration, analog callbacks and ROM division are retained. FoA/sys pins are unchanged.

## Software and linked images

- All 16 immutable build source/lock records and composed allocation gates pass.
- 2,182 per-chip original-instruction cases pass at O0/O2: all 218/181 instructions and 14/12 conditional edges covered.
- Fourteen oracle tests and nine new allocation tests pass normal and optimized Python. All 321 allocation tests, earlier host regressions and ESP32/S2 compatibility checks pass.
- Eight emitted source profiles pass 17,456 native case executions across 16 bodies. Actual instructions, literals, MMIO/state order, callback generations and consumed private input bytes are checked.
- Every retained calibration input name remains. C3 `rfcal_rxiq` grows by 2 bytes: its correction call expands from compressed JAL to JAL. All other instructions and logical call targets in that body are checked across four profiles; other retained input sizes are unchanged. Earlier IRAM entry/state ownership checks remain enforced.

| Chip/profile | Vendor PHY before → after | RX calibration before → after |
|---|---:|---:|
| esp32c3 ordinary | 9928 → 9326 B | 4900 → 4298 B |
| esp32c3 GTK | 9928 → 9326 B | 4900 → 4298 B |
| esp32s3 ordinary | 8751 → 8245 B | 4937 → 4431 B |
| esp32s3 GTK | 8743 → 8241 B | 4929 → 4427 B |

## Paired device trials

All eight lifetime/RX trials complete: three PHY lifetimes, callback bindings, beacon reception, pending buffers, exhaustion recovery and transmission checks. Configuration and TX-gain fingerprints are reported for both sides. The lifetime probe supplies deliberately invalid input calibration data; all three subsequent PHY cycles complete and receive beacons.

| Chip | Trial | Router echoes | Gateway echoes | Broadcast | Multicast | GTK rotations |
|---|---|---:|---:|---:|---:|---:|
| esp32c3 | control-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32c3 | source-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32c3 | control-gtk-v1 | 300/300 | 20/20 | 120 | 120 | 3 |
| esp32c3 | source-gtk-v1 | 300/300 | 20/20 | 119 | 120 | 2 |
| esp32c3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | control-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | source-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | control-gtk-v1 | 300/300 | 20/20 | 120 | 120 | 3 |
| esp32s3 | source-gtk-v1 | 300/300 | 20/20 | 119 | 120 | 3 |
| esp32s3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |

Across all 18 trials including restoration: router 1440/1440, gateway 320/320, broadcast 478/480, multicast 480/480, GTK rotations 11/12. Every completed trial is retained; no retry-until-pass selection.

Retained loss — esp32c3 source-gtk-v1: router sequences []; group gaps {'broadcast': [21], 'multicast': []}.

Retained loss — esp32s3 source-gtk-v1: router sequences []; group gaps {'broadcast': [34], 'multicast': []}.

esp32c3 source-gtk-v1: accepted GTK request counters [2] are absent from the AP capture; only 2/3 rotations completed. Completion events are recorded in the numerical report. Local transmit completion does not establish AP receipt; this remains unresolved.

esp32c3 source-gtk-v1 group 0 sequence 21: present at eth10/br0=True/True, 222.384 ms after the preceding G2. Its paired group frame was sent 0.088 ms later. Timing alone does not establish cause.

esp32s3 source-gtk-v1 group 0 sequence 34: present at eth10/br0=True/True, 6657.627 ms after the preceding G2. Its paired group frame was sent 0.077 ms later. Timing alone does not establish cause.

Similar broadcast gaps and locally successful GTK requests absent at the AP were documented in [the earlier basic-helper comparison](PHY-BASIC-VALIDATION.md). This observation does not determine whether the current IQ change affects their rate. Bounded completion windows do not uniquely identify every concurrent frame.

Independent raw-pcap review checks echoes, group delivery, EAPOL order and captured request/response intervals. Capture health is included in the numerical report. AP Ethernet captures do not locate a loss within RF, MAC, driver, stack or response transmission.

## Timing and limits

- esp32c3: control/source maximum PHY 85/84 µs; TX resume 1321/1435 µs.
- esp32s3: control/source maximum PHY 96/87 µs; TX resume 1563/408 µs.

Quiet logging and 80 MHz CPU settings are matched. Cumulative timing includes preemption and cannot identify individual packet causes. Per-frame GTK INFO logging remains an unresolved measurement interference concern. One board per chip, one AP and room-temperature tests do not establish calibrated RF, analog, cycle or long-duration reliability equivalence.

Ordinary source applications are restored on both boards. App slots only; forced chip/security checks and verified S3 signatures. Owned router workers/files removed, monitor disabled, persistent AP configuration unchanged. C3 completed and disconnected; paired flashing leaves S3 held in ROM with its ordinary source application retained.

See [numerical evidence](phy-rx-iq-validation.json), [implementation notes](PHY-RX-IQ.md) and [oracle](tests/phy-rx-iq-oracle/README.md).
