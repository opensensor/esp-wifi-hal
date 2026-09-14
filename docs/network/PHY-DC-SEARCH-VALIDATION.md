# Receive DC-search validation — C3 and S3

Implementation `923dd2eba105269dcd06d24c2167e6d847c29158`; control `3223e798b715cb8c01601d8616d237bb4a6fe0c2` with the identical passive lifetime probe.

The general and one-step receive DC searches now run in Rust on both chips. Two C3 / four S3 RX calibration bodies remain, plus TX calibration and analog/ROM dependencies. FoA and sys pins are unchanged.

## Software and linked images

- All 16 immutable source/lock records and composed ownership gates pass.
- Production Rust matches 2,016 cases per chip at O0/O2, covering all 664/656 original instructions and 122/100 conditional edges.
- Fifteen oracle tests, eleven new allocation tests and all 354 allocation tests pass normal and optimized Python. Earlier host regressions and ESP32/S2 compatibility checks pass.
- Eight emitted source profiles pass 16,128 case executions across sixteen bodies. All emitted instructions and conditional edges are covered, without coverage exemptions.
- Signed narrowing, wrapping arithmetic, policy thresholds, last-written exhaustion outputs, live callback dispatch and caller-buffer overlap are checked. The minimum selector remains a separately validated source boundary; its unused argument is canonicalized.
- The six-byte coarse-gain table is pinned to the original ELF/map. Supported indices are 0 through 5; out-of-domain synthetic reads are rejected. Analog/RF behavior is outside the model.

| Chip/profile | Vendor PHY before → after | RX calibration before → after |
|---|---:|---:|
| esp32c3 ordinary | 8500 → 6566 B | 3472 → 1538 B |
| esp32c3 GTK | 8500 → 6566 B | 3472 → 1538 B |
| esp32s3 ordinary | 7663 → 5915 B | 3849 → 2101 B |
| esp32s3 GTK | 7659 → 5911 B | 3845 → 2097 B |

## Paired device trials

All eight lifetime/RX trials complete: three PHY lifetimes, callback bindings, beacon reception, pending buffers, exhaustion recovery and transmission checks. The passive DC-entry probe checks bindings, not per-call execution counts. Initialization and TX-gain fingerprints are compared separately. The lifetime probe starts with deliberately invalid calibration data; all three PHY cycles complete and receive beacons.

| Chip | Trial | Router echoes | Gateway echoes | Broadcast | Multicast | GTK rotations |
|---|---|---:|---:|---:|---:|---:|
| esp32c3 | control-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32c3 | source-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32c3 | control-gtk-v1 | 300/300 | 20/20 | 118 | 120 | 3 |
| esp32c3 | source-gtk-v1 | 300/300 | 20/20 | 120 | 120 | 3 |
| esp32c3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | control-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | source-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | control-gtk-v1 | 300/300 | 20/20 | 120 | 120 | 3 |
| esp32s3 | source-gtk-v1 | 300/300 | 20/20 | 120 | 120 | 3 |
| esp32s3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |

Across all 18 trials including restoration: router 1440/1440, gateway 320/320, broadcast 478/480, multicast 480/480, GTK rotations 12/12. Every completed trial is retained; no retry-until-pass selection.

Retained loss — esp32c3 control-gtk-v1: router sequences []; group gaps {'broadcast': [12, 73], 'multicast': []}.

esp32c3 control-gtk-v1 group 0 sequence 12: present at eth10/br0=True/True, before the first captured G2. Its paired group frame was sent 0.114 ms later. Timing alone does not establish cause.

esp32c3 control-gtk-v1 group 0 sequence 73: present at eth10/br0=True/True, 6237.727 ms after the preceding G2. Its paired group frame was sent 0.088 ms later. Timing alone does not establish cause.

Independent raw-pcap review checks echoes, group delivery, EAPOL order and captured request/response intervals. Capture health is included in the numerical report. AP Ethernet captures do not locate a loss within RF, MAC, driver, stack or response transmission.

## Timing and limits

- esp32c3: control/source maximum PHY 85/89 µs; TX resume 1509/1747 µs.
- esp32s3: control/source maximum PHY 89/97 µs; TX resume 2596/2629 µs.
- esp32c3: control/source router RTT median 4.049/8.747 ms; p95 16.629/29.472 ms; maximum 62.863/172.641 ms. These finite samples do not establish a timing improvement or regression.
- esp32s3: control/source router RTT median 11.376/5.750 ms; p95 26.342/33.377 ms; maximum 54.923/69.806 ms. These finite samples do not establish a timing improvement or regression.

Quiet logging and 80 MHz CPU settings are matched. Cumulative timing includes preemption and cannot identify individual packet causes. Per-frame GTK INFO logging remains an unresolved measurement interference concern. One board per chip, one AP and room-temperature tests do not establish calibrated RF, analog, cycle or long-duration reliability equivalence.

Ordinary source applications are restored on both boards. App slots only; forced chip/security checks and verified S3 signatures. Owned router workers/files removed, monitor disabled, persistent AP configuration unchanged. C3 completed and disconnected; paired flashing leaves S3 held in ROM with its ordinary source application retained.

See [numerical evidence](phy-dc-search-validation.json), [implementation notes](PHY-DC-SEARCH.md) and [oracle](tests/phy-dc-search-oracle/README.md).
