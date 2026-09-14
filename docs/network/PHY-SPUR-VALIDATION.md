# S3 RX spur validation

Implementation `af7128ad2627dcec631a93b12c0cc37194f42620`; control `943b6758c8919de2c0acc2976dff14b559c611a6` with the identical passive lifetime probe.

The two remaining S3 RX spur routines now run in Rust. Neither C3 nor S3 retains an RX-calibration archive member, including its mergeable strings. TX calibration and analog/ROM dependencies remain. FoA and sys pins are unchanged.

## Software and linked images

- All ten immutable source/lock records and composed ownership gates pass.
- Production Rust matches 4,308 original S3 cases at O0/O2, covering all 237 original instructions and 30 conditional edges.
- Seventeen oracle tests, thirteen new allocation tests and all 380 allocation tests pass normal and optimized Python. All 31 earlier host regression steps and ESP32/S2 compatibility checks pass.
- Four emitted S3 application profiles pass 17,232 case executions across eight bodies. Every profile covers all 319 emitted instructions and 36 conditional edges, without coverage exemptions.
- The seven-argument ABI, signed channel masks, live callback dispatch, wrapped wide arithmetic with carry and early sampling exits are checked. Thirty-two zero-divisor cases preserve prior effects and the Xtensa QUOS exception boundary; exception frames and handlers are outside the model.
- Original literals and formats are pinned to the ELF/map and freshly re-extracted. All retained TX input names and sizes are identical between each control/source pair. Analog/RF behavior is outside the instruction model.

| Chip/profile | Vendor PHY before → after | RX calibration before → after |
|---|---:|---:|
| esp32c3 ordinary | 5028 → 5028 B | 0 → 0 B |
| esp32s3 ordinary | 4464 → 3814 B | 650 → 0 B |
| esp32s3 GTK | 4460 → 3814 B | 646 → 0 B |

C3 has two compatibility builds and one source restoration trial; it has no spur implementation change or paired GTK trial in this milestone.

## Paired device trials

All four S3 lifetime/RX trials complete: three PHY lifetimes, callback bindings, beacon reception, pending buffers, exhaustion recovery and transmission checks. The passive spur entry probe checks bindings, not per-call execution counts. Initialization and TX-gain fingerprints are compared separately. The lifetime probe starts with deliberately invalid calibration data; all three PHY cycles complete and receive beacons.

| Chip | Trial | Router echoes | Gateway echoes | Broadcast | Multicast | GTK rotations |
|---|---|---:|---:|---:|---:|---:|
| esp32s3 | control-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | source-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | control-gtk-v1 | 299/300 | 20/20 | 119 | 120 | 3 |
| esp32s3 | source-gtk-v1 | 300/300 | 20/20 | 120 | 120 | 3 |
| esp32s3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |
| esp32c3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |

Across all ten trials including restoration: router 759/760, gateway 200/200, broadcast 239/240, multicast 240/240, GTK rotations 6/6. Every completed trial is retained; no retry-until-pass selection.

Retained loss — esp32s3 control-gtk-v1: router sequences [177]; group gaps {'broadcast': [42], 'multicast': []}.

esp32s3 control-gtk-v1 group 0 sequence 42: present at eth10/br0=True/True, 684.011 ms after the preceding G2. Its paired group frame was sent 0.118 ms later. Timing alone does not establish cause.

Independent raw-pcap review checks echoes, group delivery, EAPOL order and captured request/response intervals. Capture health is included in the numerical report. AP Ethernet captures do not locate a loss within RF, MAC, driver, stack or response transmission.

## Timing and limits

- esp32s3: control/source maximum PHY 100/100 µs; TX resume 2605/2401 µs.
- esp32s3: control/source router RTT median 4.441/3.245 ms; p95 29.989/50.444 ms; maximum 67.328/111.715 ms. These finite samples do not establish a timing improvement or regression.

Quiet logging and 80 MHz CPU settings are matched. Cumulative timing includes preemption and cannot identify individual packet causes. Per-frame GTK INFO logging remains an unresolved measurement interference concern. One board per chip, one AP and room-temperature tests do not establish calibrated RF, analog, cycle or long-duration reliability equivalence.

Ordinary source applications are restored on both boards. App slots only; forced chip/security checks and verified S3 signatures. Owned router workers/files removed, monitor disabled, persistent AP configuration unchanged. C3 completed and disconnected; paired flashing leaves S3 held in ROM with its ordinary source application retained.

See [numerical evidence](phy-spur-validation.json), [implementation notes](PHY-SPUR.md) and [oracle](tests/phy-spur-oracle/README.md).
