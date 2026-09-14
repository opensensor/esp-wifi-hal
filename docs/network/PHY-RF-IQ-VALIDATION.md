# RF-IQ validation — C3 and S3

Implementation `84014cec9344443880d578d437ea386d2963589a`; control `e8cdd69535fc424b81f9b3502826f6bf2c44a99c` with the identical passive lifetime probe. The tightened allocation auditor is `84014cec9344443880d578d437ea386d2963589a`.

Two RF-IQ orchestration/convergence routines per chip are Rust. The remaining 6 C3 / 8 S3 RX calibration bodies, TX calibration, analog callbacks and ROM dependencies are retained. FoA/sys pins are unchanged.

## Software and linked images

- All 16 immutable build source/lock records and composed allocation gates pass.
- 5,031 per-chip original-instruction cases pass at O0/O2: all 162/119 instructions and 18/10 conditional edges under the conservative boundary contract covered.
- Twelve oracle tests and eleven new allocation tests pass normal and optimized Python. All 332 allocation tests, earlier host regressions and ESP32/S2 compatibility checks pass.
- Eight emitted source profiles pass 40,248 native case executions across 16 bodies. Actual instructions, literals, MMIO/state order, callback generations and consumed private input bytes are checked.
- Every retained calibration input name and size is unchanged across the four matched profiles. Earlier IRAM entry/state ownership checks remain enforced.
- Cases separate arbitrary signed-byte correction outputs from the proven -31..31 output range. Four original C3 clamp paths are unreachable under that narrower contract; this is not a full analog composition proof.

| Chip/profile | Vendor PHY before → after | RX calibration before → after |
|---|---:|---:|
| esp32c3 ordinary | 9326 → 8918 B | 4298 → 3890 B |
| esp32c3 GTK | 9326 → 8918 B | 4298 → 3890 B |
| esp32s3 ordinary | 8245 → 7919 B | 4431 → 4105 B |
| esp32s3 GTK | 8241 → 7915 B | 4427 → 4101 B |

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
| esp32s3 | control-gtk-v1 | 300/300 | 20/20 | 120 | 120 | 3 |
| esp32s3 | source-gtk-v1 | 300/300 | 20/20 | 120 | 120 | 3 |
| esp32s3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |

Across all 18 trials including restoration: router 1440/1440, gateway 320/320, broadcast 480/480, multicast 480/480, GTK rotations 12/12. Every completed trial is retained; no retry-until-pass selection.

esp32c3 control-gtk-v1: G1 counters [3] have no corresponding G2 in the AP capture. The numerical report retains subsequent retries, non-reinstalled updates and completed request intervals. This does not locate the missing response within RF, MAC or the AP path.

esp32c3 source-gtk-v1: G1 counters [5] have no corresponding G2 in the AP capture. The numerical report retains subsequent retries, non-reinstalled updates and completed request intervals. This does not locate the missing response within RF, MAC or the AP path.

esp32s3 control-gtk-v1: G1 counters [3, 5] have no corresponding G2 in the AP capture. The numerical report retains subsequent retries, non-reinstalled updates and completed request intervals. This does not locate the missing response within RF, MAC or the AP path.

esp32s3 source-gtk-v1: G1 counters [5] have no corresponding G2 in the AP capture. The numerical report retains subsequent retries, non-reinstalled updates and completed request intervals. This does not locate the missing response within RF, MAC or the AP path.

No measured echo or group-UDP gaps occurred in this finite comparison. EAPOL retries are recorded separately. Earlier losses and latency tails remain open; this is not a packet-loss fix claim.

Independent raw-pcap review checks echoes, group delivery, EAPOL order and captured request/response intervals. Capture health is included in the numerical report. AP Ethernet captures do not locate a loss within RF, MAC, driver, stack or response transmission.

## Timing and limits

- esp32c3: control/source maximum PHY 87/87 µs; TX resume 1188/1326 µs.
- esp32s3: control/source maximum PHY 89/88 µs; TX resume 2589/2935 µs.
- esp32c3: control/source router RTT median 5.114/4.136 ms; p95 47.122/28.176 ms; maximum 85.055/167.107 ms. These finite samples do not establish a timing improvement or regression.
- esp32s3: control/source router RTT median 3.632/6.660 ms; p95 19.711/33.962 ms; maximum 97.400/102.131 ms. These finite samples do not establish a timing improvement or regression.

Quiet logging and 80 MHz CPU settings are matched. Cumulative timing includes preemption and cannot identify individual packet causes. Per-frame GTK INFO logging remains an unresolved measurement interference concern. One board per chip, one AP and room-temperature tests do not establish calibrated RF, analog, cycle or long-duration reliability equivalence.

Ordinary source applications are restored on both boards. App slots only; forced chip/security checks and verified S3 signatures. Owned router workers/files removed, monitor disabled, persistent AP configuration unchanged. C3 completed and disconnected; paired flashing leaves S3 held in ROM with its ordinary source application retained.

See [numerical evidence](phy-rf-iq-validation.json), [implementation notes](PHY-RF-IQ.md) and [oracle](tests/phy-rf-iq-oracle/README.md).
