# C3/S3 TX detector validation

Implementation `efb1816480bfa10f11ef14b81ced021e4a5bb1b6`; control `19d53bdfc092ba0870958f5f4c687de2ed1d546c` with the identical passive lifetime probe.

The TX detector reference and calibration routines now run in Rust on C3 and S3. Sixteen other TX calibration routines retain vendor ownership on each chip. RX-calibration archive members remain absent. FoA and sys pins are unchanged.

## Software and linked images

- All sixteen immutable source/lock records and composed ownership gates pass.
- Production Rust matches 1,040 original cases per chip at O0/O2, covering all 63 C3 and 50 S3 original instructions and both conditional edges per chip.
- Eleven oracle tests, thirteen new allocation tests and all 393 allocation tests pass normal and optimized Python. All 32 earlier host regression steps and ESP32/S2 compatibility checks pass.
- Eight emitted application profiles pass 8,320 case executions. Every emitted instruction and conditional edge is covered, including outlined Rust reference helpers.
- Checks preserve argument narrowing, ordered volatile accesses, fresh helper-mutated register and flag reads, chip-specific calibration codes and the different second-sample store/read order. Analog and RF behavior is outside the instruction model.
- Originals are freshly re-extracted and pinned to ELF/map hashes. Retained TX input names are preserved. C3 tx_pwctrl_init grows two bytes in each profile: a call to pwdet_ref_code changes from a two-byte to a four-byte encoding. Full-body comparison preserves other normalized instructions, logical call targets and internal branch targets. S3 retained input sizes are unchanged.

| Chip/profile | Vendor PHY before → after | Removed detector text |
|---|---:|---:|
| esp32c3 ordinary | 5028 → 4852 B | 178 B |
| esp32c3 GTK | 5028 → 4852 B | 178 B |
| esp32s3 ordinary | 3814 → 3663 B | 151 B |
| esp32s3 GTK | 3814 → 3663 B | 151 B |

These totals describe retained vendor PHY inputs, not total firmware size. C3 savings include the two-byte retained call expansion.

## Paired device trials

All eight C3/S3 lifetime/RX trials complete: three PHY lifetimes, callback bindings, beacon reception, pending buffers, exhaustion recovery and transmission checks. The passive detector entry probe checks bindings, not per-call execution counts. Initialization and TX-gain fingerprints match control on both chips. The lifetime probe starts with deliberately invalid calibration data; all three PHY cycles complete and receive beacons.

| Chip | Trial | Router echoes | Gateway echoes | Broadcast | Multicast | GTK rotations |
|---|---|---:|---:|---:|---:|---:|
| esp32c3 | control-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32c3 | source-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32c3 | control-gtk-v1 | 300/300 | 20/20 | 120 | 120 | 3 |
| esp32c3 | source-gtk-v1 | 300/300 | 20/20 | 120 | 120 | 3 |
| esp32c3 | source-restored-v1 | 40/40 | 39/40 | — | — | — |
| esp32s3 | control-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | source-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | control-gtk-v1 | 299/300 | 20/20 | 120 | 120 | 3 |
| esp32s3 | source-gtk-v1 | 300/300 | 20/20 | 120 | 120 | 3 |
| esp32s3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |

Across all eighteen trials including restoration: router 1439/1440, gateway 319/320, broadcast 480/480, multicast 480/480, GTK rotations 12/12. The C3 restoration smoke test failed its gateway-loss assertion after both cycles disconnected. Seventeen trials reached completion markers; all eighteen attempts are retained without retry-until-pass selection.

Retained loss — esp32s3 control-gtk-v1: router sequences [58]; group gaps {'broadcast': [], 'multicast': []}.

esp32s3 control-gtk-v1 echo 58: request present at both AP Ethernet interfaces, with no matching reply. The request follows the preceding G2 by 1.569540 seconds. Adjacent echo details remain in the numerical report; temporal proximity does not establish cause.

C3 restoration is a failed smoke test: 39/40 gateway replies, followed by the explicit Gateway echo loss assertion. Gateway sequence 8 from cycle 1 is absent from both AP Ethernet captures; all 39 captured gateway requests have matching replies. Both application cycles disconnected, and the original failing result and terminal assertion are retained. Ethernet captures do not locate the loss before AP receipt.

Independent raw-pcap review checks echoes, group delivery, EAPOL order and captured request/response intervals. Capture health is included in the numerical report. AP Ethernet captures do not locate a loss within RF, MAC, driver, stack or response transmission.

## Timing and limits

- esp32c3: control/source maximum PHY 87/89 µs; TX resume 1617/2120 µs.
- esp32s3: control/source maximum PHY 97/92 µs; TX resume 3391/1547 µs.
- esp32c3: control/source router RTT median 4.525/10.626 ms; p95 19.236/28.644 ms; maximum 83.425/92.632 ms. These finite samples do not establish a timing improvement or regression.
- esp32s3: control/source router RTT median 5.276/2.967 ms; p95 31.081/13.429 ms; maximum 84.015/106.092 ms. These finite samples do not establish a timing improvement or regression.

Quiet logging and 80 MHz CPU settings are matched. Cumulative timing includes preemption and cannot identify individual packet causes. Per-frame GTK INFO logging remains an unresolved measurement interference concern. One board per chip, one AP and room-temperature tests do not establish calibrated RF, analog, cycle or long-duration reliability equivalence.

Ordinary source images remain installed on both boards. App slots only; forced chip/security checks and verified S3 signatures. Owned router workers/files removed, monitor disabled, persistent AP configuration unchanged. C3 completed both disconnects and is halted at its explicit gateway-loss test assertion; paired flashing leaves S3 held in ROM with its ordinary source application retained.

See [numerical evidence](phy-tx-detector-validation.json), [implementation notes](PHY-TX-DETECTOR.md) and [oracle](tests/phy-tx-detector-oracle/README.md).
