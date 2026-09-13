# PHY power detector: C3/S3 source and device comparison

The [Rust power-detector implementation](PHY-PWDET.md), commit
`31db517d890735d8a5f94efcf7365ee61cb9ccdd`, removes every allocated `phy_pwdet.o` input
in the compared images. Control `99adf07` retains the original power detector
and all earlier MAC/PHY replacements. Both sides use the identical expanded
lifetime probe. The [numeric report](phy-pwdet-validation.json) records
build hashes, linked ownership, native review and actual traffic results.

FoA remains `c433109960bc2b346a45da47c2bd3d2cb32690bf`, including the
[EAPOL completion correction](EAPOL-TX-COMPLETION.md); sys remains
`73add8985cec3b7582e6df80a4273022deb844b0`. All sixteen builds use the committed
dependency lock. Every recorded source hash was checked against the
implementation commit or control with the explicit common probe overlay.
Both sides use 80 MHz, quiet timing logs and unchanged RF tracking cadence.
Original vendor archives are unchanged.

## Linked ownership and instruction behavior

| Chip | Control vendor PHY bytes | Source vendor PHY bytes | Removed power-detector bytes | PHY members |
| --- | ---: | ---: | ---: | --- |
| esp32c3 | 29,731 | 29,141 | 588 | 11 → 10 |
| esp32s3 | 28,276 | 27,898 | 378 | 11 → 10 |

S3 GTK totals are 28,268 → 27,890; C3 totals are the same in ordinary and GTK
profiles. The C3 decrease includes two additional bytes in retained
`phy_rfpll.o`: a call to the same `wr_rx_gain_mem` target relaxes from JAL to
C.JAL. Normalized instructions, named call targets and the moved nine-byte
memcpy table are checked. No other retained input changes identity or size.
These are allocated non-string vendor inputs, not whole-image savings;
the Rust bodies also occupy memory.

All eight full station/GTK audits pass, composing the earlier formatter,
wrapper, dispatcher, temperature, sensor, PBUS, I2C, API, basic, feature and
debug gates. No prior ownership exception was needed. Every power-detector
input, including literals and excluded mergeable strings, must be absent.
No `libpp.a` input is allocated. Eight reduced lifetime/RX profiles separately
pass source ownership and earlier absent-member checks; these are not full
station audits.

Production matches **913,536 original-instruction cases at O0 and O2**:
457,298 C3 and 456,238 S3 cases. Twenty-one focused oracle tests and all 171
allocation regressions pass normally and with Python assertions disabled.
ESP32 and S2 compatibility checks pass; those chips were not tested on hardware.
Coverage includes parameter/output aliases, signed arithmetic, callback
reloads and mutations, nested helpers, all eight callback output stores,
readiness polling schedules, sample-count narrowing and counter wrapping.
C3 has 37 bounded non-completing prefixes; S3 has eighteen plus eight native
divide-exception cases. These outcomes are recorded separately from returns.
Host instruction and event budgets are not production timeouts.

Native review covers 68 source bodies across four profiles per chip. All
nine C3 and eight S3 entries remain in flash. It checks strong aliases,
source helper calls, callback-slot loads, sixteen-byte sample buffers and
alignment, and separation from explicit stack spills. S3 sampling retains
a native QUOU division. The linear helper's compiler-generated panic branch
is unreachable under the verified local nonzero-denominator contract.
Stack frames, instruction counts and barriers differ from the original;
this is not cycle or analog equivalence.

## Lifetime, ROM boundary and RX probes

All four lifetime trials complete three PHY guard cycles, nonempty
calibration, sensor shutdown and all previous probes. The new stage checks
ten pure reference vectors per cycle with destination guard halfwords and
compares selected entry addresses against the ELF. Four callback slots are
recorded each cycle. This probe adds no tones, ADC collections or parameter
writes; the usual driver workload still performs calibration and operation.

| Chip | Implementation | Reference vectors passed | Callback observations | Beacons after wakeup | RX frames / OFDM |
| --- | --- | ---: | ---: | ---: | --- |
| esp32c3 | control | 30 | 12 | 2 | 10 / 2 |
| esp32c3 | source | 30 | 12 | 2 | 10 / 2 |
| esp32s3 | control | 30 | 12 | 2 | 7 / 0 |
| esp32s3 | source | 30 | 12 | 2 | 8 / 2 |

All four RX probes preserve pending buffers, recover from exhaustion and
transmit OFDM. Previous temperature, sensor, PBUS, I2C, API, basic, feature
and debug observations remain in the numeric report. The power-detector
callback targets agree across all three cycles with their respective ELFs:

| Chip | Setup | Output buffer | Read wrapper | Conversion |
| --- | --- | --- | --- | --- |
| esp32c3 source | `0x4201ba52` | `0x4003a2cc` | `0x4201bac6` | `0x40039ff2` |
| esp32s3 source | `0x40036a18` | `0x40036aa4` | `0x4201a7b0` | `0x40036794` |

C3 setup and both read wrappers select source. The other numeric targets
remain ROM dependencies. The observed output callbacks write eight
halfwords, although the wrapper returns only the second. Installed C3
rev0/rev3/rev101 output bodies are byte-identical; the S3 body implements the
same eight-word register read and thirteen-bit masking boundary. The
[ROM buffer evidence](tests/phy-pwdet-oracle/rom-buffer-boundary.json) records
body bytes, hashes and instructions. This establishes the local buffer
contract, not analog accuracy or complete ROM replacement.

## Traffic and key rotation

Ordinary and restored-source trials each make two connections. Each GTK trial
makes one connection, sends 300 router echoes with 512-byte payloads and twenty
gateway echoes, and sends 120 broadcasts plus 120 multicasts with 128-byte
payloads while requesting three group-key rotations.

| Chip | Trial | Router echoes | Gateway echoes | Broadcast | Multicast | Median / maximum router RTT (ms) |
| --- | --- | --- | --- | --- | --- | --- |
| esp32c3 | control-normal-v3 | 40/40 | 40/40 | — | — | 8.787 / 104.699 |
| esp32c3 | source-normal-v1 | 40/40 | 40/40 | — | — | 7.725 / 87.992 |
| esp32c3 | control-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 9.286 / 147.863 |
| esp32c3 | source-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 7.798 / 148.258 |
| esp32c3 | source-restored-v1 | 40/40 | 40/40 | — | — | 11.254 / 69.598 |
| esp32s3 | control-normal-v1 | 40/40 | 40/40 | — | — | 14.007 / 91.678 |
| esp32s3 | source-normal-v1 | 40/40 | 40/40 | — | — | 8.460 / 96.466 |
| esp32s3 | control-gtk-v1 | 300/300 | 20/20 | 119/120 | 119/120 | 12.765 / 182.337 |
| esp32s3 | source-gtk-v1 | 300/300 | 20/20 | 119/120 | 120/120 | 7.115 / 130.220 |
| esp32s3 | source-restored-v1 | 40/40 | 40/40 | — | — | 5.245 / 47.799 |

A separate raw-pcap reader corroborates echo payload pairs, group sequences
and EAPOL counters. `eth10` captures both EAPOL directions; `br0` corroborates
station requests/replies but does not capture AP-originated G1. All capture
workers report zero drops, truncation and missing timestamps. Every completed
trial is retained, including packet gaps or incomplete rotations.

| Chip / GTK trial | Completed rotations / requested | Request counters absent at AP | Missing broadcast / multicast sequences | G1-to-G2 latency (ms, by counter) |
| --- | --- | --- | --- | --- |
| esp32c3 / control-gtk-v1 | 3/3 | `[]` | `[]` / `[]` | `{'3': 16.66, '4': 37.556, '5': 18.602}` |
| esp32c3 / source-gtk-v1 | 3/3 | `[]` | `[]` / `[]` | `{'3': 17.563, '4': 19.078, '5': 14.143}` |
| esp32s3 / control-gtk-v1 | 3/3 | `[]` | `[44]` / `[19]` | `{'3': 34.138, '4': 20.338, '5': 82.233}` |
| esp32s3 / source-gtk-v1 | 3/3 | `[]` | `[23]` / `[]` | `{'3': 31.793, '4': 50.927, '5': 19.599}` |

- `esp32s3/control-gtk-v1` misses broadcast sequence 44; present in `eth10`: `True`, `br0`: `True`. It occurs 1676.787 ms after completed G2 counter 4; paired group capture separation is 0.112 ms.
- `esp32s3/control-gtk-v1` misses multicast sequence 19; present in `eth10`: `True`, `br0`: `True`. It occurs before the first completed group-key rotation; paired group capture separation is -0.083 ms.
- `esp32s3/source-gtk-v1` misses broadcast sequence 23; present in `eth10`: `True`, `br0`: `True`. It occurs 1224.37 ms after completed G2 counter 3; paired group capture separation is 0.105 ms.

AP Ethernet observations do not locate RF/device losses or prove their cause.
A reported MAC success is not proof of AP acceptance. Historical packet gaps
and timing tails remain open, including the [debug comparison](PHY-DEBUG-VALIDATION.md).
Successful traffic here does not establish that removing this member fixes
those observations or proves long-duration reliability.

Two C3 control setup attempts were aborted before an application flash or
station traffic: missing capture tools, then executable preflight rejection
after an unsupported SFTP transfer. The tools were staged with legacy SCP
and their hashes verified. The completed control trial retains label
`control-normal-v3` and uses the original control-v1 image. Both aborted
attempts and their evidence hashes remain in the numeric report; no traffic
result was discarded or overwritten.

## Restoration and remaining work

Both boards were restored to ordinary source station images and passed two
additional connections each. Every flash checked forced chip identity and
security state; S3 app images were signed and verified with the existing key.
Only existing application slots were written. Owned router workers and
temporary files were removed; monitor mode remains zero and persistent AP
configuration is unchanged. C3 finished disconnected; the final paired
flasher holds S3 in ROM. Both retain ordinary source application images.

Ten vendor PHY members remain: analog calibration, tracking, TX gain, PLL,
RX gain, register programming, frequency control, RF initialization, TX
calibration and RX calibration. Vendor state and ROM ADC/conversion callbacks
remain. This milestone covers one board per chip, one AP and short trials.
Calibrated RF/power accuracy, other temperatures, sleep/coexistence and
long-duration reliability remain unvalidated.
