# Receive gain-calibration validation — C3 and S3

Implementation `2839a19e1af9a80c36ebffef380c6b0c73900763`; control `86ac8bfe0f337006426bd3843e46dae91bcd966a` with the identical passive lifetime probe.

Receive gain IQ/DC calibration now runs in Rust on both chips. C3 has no remaining RX-calibration archive member; S3 retains two spur helpers. TX calibration and analog/ROM dependencies remain. FoA and sys pins are unchanged.

## Software and linked images

- All 16 immutable source/lock records and composed ownership gates pass.
- Production Rust matches 1,395 C3 / 1,516 S3 cases at O0/O2. C3 executes 569/570 original instructions and 59/60 conditional edges; an exhaustive four-attempt proof excludes only the unreachable upper clamp. S3 executes all 520 instructions and 54 edges.
- Seventeen oracle tests, thirteen new allocation tests and all 367 allocation tests pass normal and optimized Python. Earlier host regressions and ESP32/S2 compatibility checks pass.
- Eight emitted source profiles pass 11,644 case executions across sixteen bodies. All emitted instructions and conditional edges are covered, without coverage exemptions.
- Scalar narrowing, zero counts, signed packed outputs, seven-channel layouts, carried coefficients, live callback dispatch and caller-buffer overlap are checked. The S3 ABI consumes nine of ten supplied arguments.
- Original readonly tables and formats are pinned to the ELF/map. The stage/count and pointer domains are explicit; invalid domains are rejected. Analog/RF behavior is outside the model.

| Chip/profile | Vendor PHY before → after | RX calibration before → after |
|---|---:|---:|
| esp32c3 ordinary | 6566 → 5028 B | 1538 → 0 B |
| esp32c3 GTK | 6566 → 5028 B | 1538 → 0 B |
| esp32s3 ordinary | 5915 → 4464 B | 2101 → 650 B |
| esp32s3 GTK | 5911 → 4460 B | 2097 → 646 B |

## Paired device trials

All eight lifetime/RX trials complete: three PHY lifetimes, callback bindings, beacon reception, pending buffers, exhaustion recovery and transmission checks. The passive gain-calibration entry probe checks bindings, not per-call execution counts. Initialization and TX-gain fingerprints are compared separately. The lifetime probe starts with deliberately invalid calibration data; all three PHY cycles complete and receive beacons.

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
| esp32s3 | source-gtk-v1 | 300/300 | 20/20 | 120 | 120 | 3 |
| esp32s3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |

Across all 18 trials including restoration: router 1440/1440, gateway 320/320, broadcast 479/480, multicast 480/480, GTK rotations 12/12. Every completed trial is retained; no retry-until-pass selection.

Retained loss — esp32s3 control-gtk-v1: router sequences []; group gaps {'broadcast': [21], 'multicast': []}.

esp32s3 control-gtk-v1 group 0 sequence 21: present at eth10/br0=True/True, 158.071 ms after the preceding G2. Its paired group frame was sent 0.103 ms later. Timing alone does not establish cause.

Independent raw-pcap review checks echoes, group delivery, EAPOL order and captured request/response intervals. Capture health is included in the numerical report. AP Ethernet captures do not locate a loss within RF, MAC, driver, stack or response transmission.

## Timing and limits

- esp32c3: control/source maximum PHY 86/86 µs; TX resume 1134/1101 µs.
- esp32s3: control/source maximum PHY 89/87 µs; TX resume 2459/1562 µs.
- esp32c3: control/source router RTT median 8.043/5.431 ms; p95 21.140/24.778 ms; maximum 65.606/73.208 ms. These finite samples do not establish a timing improvement or regression.
- esp32s3: control/source router RTT median 3.167/4.239 ms; p95 63.917/28.256 ms; maximum 140.215/78.176 ms. These finite samples do not establish a timing improvement or regression.

Quiet logging and 80 MHz CPU settings are matched. Cumulative timing includes preemption and cannot identify individual packet causes. Per-frame GTK INFO logging remains an unresolved measurement interference concern. One board per chip, one AP and room-temperature tests do not establish calibrated RF, analog, cycle or long-duration reliability equivalence.

Ordinary source applications are restored on both boards. App slots only; forced chip/security checks and verified S3 signatures. Owned router workers/files removed, monitor disabled, persistent AP configuration unchanged. C3 completed and disconnected; paired flashing leaves S3 held in ROM with its ordinary source application retained.

See [numerical evidence](phy-rx-gain-cal-validation.json), [implementation notes](PHY-RX-GAIN-CAL.md) and [oracle](tests/phy-rx-gain-cal-oracle/README.md).
