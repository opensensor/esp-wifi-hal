# RX DC validation — C3 and S3

Implementation `7d7164fd1ad399c0330f3e9c6403bfea2a7a4c7a`; control `8be97be804e23d47ed216e43a85cce24226dbe07` with the identical passive lifetime probe.

Receive DC minimum selection and channel filling now run in Rust on both chips. Four C3 / six S3 RX calibration bodies remain, together with TX calibration, analog callbacks and ROM dependencies. The ACK-enabled FoA and sys pins are unchanged.

## Software and linked images

- All 16 immutable source/lock records and composed ownership gates pass.
- The production Rust module matches 2,368 C3 and 1,976 S3 original-instruction cases at O0/O2. All 168/101 original instructions and 30/28 conditional edges are covered.
- Nine contract tests, four bounds-proof tests, eleven new allocation tests and all 343 allocation tests pass normal and optimized Python. Earlier host regressions and ESP32/S2 compatibility checks pass.
- Eight emitted source profiles pass 17,376 case executions across 16 bodies, checking ordered accesses, callback arguments, live table/gate mutations and consumed private buffers.
- C3 covers all 184 emitted instructions and 31 feasible conditional edges. A finite abstract execution independently proves one compiler range-check edge unreachable; twelve invalid-proof mutations are rejected. S3 covers all 145 emitted instructions and 30 conditional edges.
- All retained calibration input names are preserved. Four calls to the two new Rust routines expand from 2 to 4 bytes in each C3 profile; decoded checks preserve all other instructions, logical call targets and internal branch destinations. S3 retained input sizes are unchanged.
- C3 carries selection state between its three channel-table columns. Signed-byte callback narrowing, ties, fallback values and allowed memory overlap are checked against the original instructions. The synthetic estimator supplies all three output words; analog internals are outside the model.

| Chip/profile | Vendor PHY before → after | RX calibration before → after |
|---|---:|---:|
| esp32c3 ordinary | 8918 → 8500 B | 3890 → 3472 B |
| esp32c3 GTK | 8918 → 8500 B | 3890 → 3472 B |
| esp32s3 ordinary | 7919 → 7663 B | 4105 → 3849 B |
| esp32s3 GTK | 7915 → 7659 B | 4101 → 3845 B |

## Paired device trials

All eight lifetime/RX trials complete: three PHY lifetimes, callback bindings, beacon reception, pending buffers, exhaustion recovery and transmission checks. The passive DC-entry probe checks bindings, not per-call execution counts. Initialization and TX-gain fingerprints are compared separately. The lifetime probe starts with deliberately invalid calibration data; all three PHY cycles complete and receive beacons.

| Chip | Trial | Router echoes | Gateway echoes | Broadcast | Multicast | GTK rotations |
|---|---|---:|---:|---:|---:|---:|
| esp32c3 | control-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32c3 | source-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32c3 | control-gtk-v1 | 300/300 | 20/20 | 120 | 120 | 3 |
| esp32c3 | source-gtk-v1 | 300/300 | 20/20 | 119 | 120 | 3 |
| esp32c3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | control-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | source-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | control-gtk-v1 | 300/300 | 20/20 | 120 | 120 | 3 |
| esp32s3 | source-gtk-v1 | 300/300 | 20/20 | 120 | 120 | 3 |
| esp32s3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |

Across all 18 trials including restoration: router 1440/1440, gateway 320/320, broadcast 479/480, multicast 480/480, GTK rotations 12/12. Every completed trial is retained; no retry-until-pass selection.

Retained loss — esp32c3 source-gtk-v1: router sequences []; group gaps {'broadcast': [95], 'multicast': []}.

esp32c3 source-gtk-v1 group 0 sequence 95: present at eth10/br0=True/True, 17159.556 ms after the preceding G2. Its paired group frame was sent 0.092 ms later. Timing alone does not establish cause.

Independent raw-pcap review checks echoes, group delivery, EAPOL order and captured request/response intervals. Capture health is included in the numerical report. AP Ethernet captures do not locate a loss within RF, MAC, driver, stack or response transmission.

## Timing and limits

- esp32c3: control/source maximum PHY 87/85 µs; TX resume 1550/1695 µs.
- esp32s3: control/source maximum PHY 97/91 µs; TX resume 5706/1544 µs.
- esp32c3: control/source router RTT median 4.771/6.000 ms; p95 28.171/24.269 ms; maximum 79.091/126.166 ms. These finite samples do not establish a timing improvement or regression.
- esp32s3: control/source router RTT median 5.007/5.702 ms; p95 21.061/34.855 ms; maximum 50.050/146.215 ms. These finite samples do not establish a timing improvement or regression.

Quiet logging and 80 MHz CPU settings are matched. Cumulative timing includes preemption and cannot identify individual packet causes. Per-frame GTK INFO logging remains an unresolved measurement interference concern. One board per chip, one AP and room-temperature tests do not establish calibrated RF, analog, cycle or long-duration reliability equivalence.

Ordinary source applications are restored on both boards. App slots only; forced chip/security checks and verified S3 signatures. Owned router workers/files removed, monitor disabled, persistent AP configuration unchanged. C3 completed and disconnected; paired flashing leaves S3 held in ROM with its ordinary source application retained.

See [numerical evidence](phy-rx-dc-validation.json), [implementation notes](PHY-RX-DC.md) and [oracle](tests/phy-rx-dc-oracle/README.md).
