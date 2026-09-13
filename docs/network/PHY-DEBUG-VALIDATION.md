# PHY debug member: C3/S3 source and device comparison

The [Rust debug implementation](PHY-DEBUG.md), commit
`5038c5b8154ee8f4a8706413b94dd21c382c8b63`, removes every allocated `phy_debug.o` input
in the compared images. Control `28db5ed` retains the original debug member
and all earlier MAC/PHY replacements. Both sides use the identical expanded
lifetime probe. The [numeric report](phy-debug-validation.json) records
build hashes, linked ownership, native review and actual traffic results.

FoA remains `c433109960bc2b346a45da47c2bd3d2cb32690bf`, including the
[EAPOL completion correction](EAPOL-TX-COMPLETION.md); sys remains
`73add8985cec3b7582e6df80a4273022deb844b0`. All sixteen builds use the committed
dependency lock. Every recorded source hash was checked against the
implementation commit or control with the explicit common probe overlay.
Both sides use 80 MHz, quiet timing logs and unchanged RF tracking cadence.
Original vendor archives are unchanged.

## Linked ownership and instruction behavior

| Chip | Control vendor PHY bytes | Source vendor PHY bytes | Removed debug bytes | PHY members |
| --- | ---: | ---: | ---: | --- |
| esp32c3 | 30,101 | 29,731 | 370 | 12 → 11 |
| esp32s3 | 28,582 | 28,276 | 306 | 12 → 11 |

S3 GTK totals are 28,574 → 28,268; C3 totals are the same in ordinary and GTK
profiles. Every other retained input keeps its identity and size in both
profiles. These are allocated non-string vendor inputs, not whole-image
savings; the Rust bodies also occupy memory.

All eight full station/GTK audits pass, composing the earlier formatter,
wrapper, dispatcher, temperature, sensor, PBUS, I2C, API, basic and feature
gates. No prior ownership exception was needed. Every debug input, including
literals and excluded mergeable strings, must be absent. No `libpp.a` input
is allocated. Eight reduced lifetime/RX profiles separately pass debug
ownership and earlier absent-member checks; these are not full station audits.

Production matches **748,260 original-instruction cases at O0 and O2**:
374,130 per chip. Sixteen focused oracle tests and all 159 allocation
regressions pass normally and with Python assertions disabled. ESP32 and S2
compatibility checks pass; those chips were not tested on hardware here.
The host cases cover component sign extension, selector narrowing, callback
reloads/mutations, cleanup and raw return preservation. Voltage coverage
includes both nested bias execution and an opaque bias-return boundary,
zero bias, signed division and wrapping multiplication/overflow.

Native review covers 24 source bodies across four profiles per chip. All
three helpers remain in flash. It checks ordered callback-slot loads, six
masked-write arguments, ADC return preservation, source bias routing and
ordered IQ byte stores. Native stack usage, instruction counts and volatile
barriers differ from the original. This is not cycle or analog equivalence.

## Lifetime and RX probes

All four lifetime trials complete three PHY guard cycles, nonempty
calibration, sensor shutdown and the prior PBUS/I2C/API/basic/feature probes.
The debug stage runs ten pure IQ vectors per cycle with guard bytes around
the destination and checks the selected entry addresses against the ELF.
It also records five callback targets. It issues no additional analog
sampling or writes; observing a callback address is not proof that every
analog branch ran during the test.

| Chip | Implementation | IQ vectors passed | Callback observations | Beacons after wakeup | RX frames / OFDM |
| --- | --- | ---: | ---: | ---: | --- |
| esp32c3 | control | 30 | 15 | 2 | 8 / 0 |
| esp32c3 | source | 30 | 15 | 2 | 7 / 1 |
| esp32s3 | control | 30 | 15 | 2 | 11 / 3 |
| esp32s3 | source | 30 | 15 | 2 | 8 / 2 |

All four RX probes preserve pending buffers, recover from exhaustion and
transmit OFDM. Temperature observations and prior probe values remain in the
numeric report without a calibrated temperature/voltage accuracy claim.
The callback addresses agree across all three cycles and both implementations:

| Chip | Masked write | ADC sample | Setup entry | Setup mode | Setup exit |
| --- | --- | --- | --- | --- | --- |
| esp32c3 | `0x4003922a` | `0x4003a338` | `0x4003945c` | `0x400393ca` | `0x4003946c` |
| esp32s3 | `0x400358d8` | `0x40036afc` | `0x40035b6c` | `0x40035acc` | `0x40035b80` |

These retained callback bodies remain outside this source replacement.

## Traffic and key rotation

Ordinary and restored-source trials each make two connections. Each GTK trial
makes one connection, sends 300 router echoes with 512-byte payloads and twenty
gateway echoes, and sends 120 broadcasts plus 120 multicasts with 128-byte
payloads while requesting three group-key rotations.

| Chip | Trial | Router echoes | Gateway echoes | Broadcast | Multicast | Median / maximum router RTT (ms) |
| --- | --- | --- | --- | --- | --- | --- |
| esp32c3 | control-normal-v1 | 40/40 | 40/40 | — | — | 6.248 / 93.723 |
| esp32c3 | source-normal-v1 | 40/40 | 40/40 | — | — | 4.404 / 51.453 |
| esp32c3 | control-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 11.978 / 98.117 |
| esp32c3 | source-gtk-v1 | 300/300 | 20/20 | 119/120 | 120/120 | 5.553 / 104.383 |
| esp32c3 | source-restored-v1 | 40/40 | 40/40 | — | — | 5.133 / 56.316 |
| esp32s3 | control-normal-v1 | 40/40 | 40/40 | — | — | 3.352 / 102.240 |
| esp32s3 | source-normal-v1 | 40/40 | 40/40 | — | — | 8.098 / 61.235 |
| esp32s3 | control-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 5.588 / 93.754 |
| esp32s3 | source-gtk-v1 | 300/300 | 20/20 | 119/120 | 120/120 | 3.821 / 116.605 |
| esp32s3 | source-restored-v1 | 40/40 | 40/40 | — | — | 4.218 / 33.519 |

A separate raw-pcap reader corroborates echo payload pairs, group sequences
and EAPOL counters. `eth10` captures both EAPOL directions; `br0` corroborates
station requests/replies but does not capture AP-originated G1. All capture
workers report zero drops, truncation and missing timestamps. Every completed
trial is retained, including packet gaps or incomplete rotations.

| Chip / GTK trial | Completed rotations / requested | Request counters absent at AP | Missing broadcast / multicast sequences | G1-to-G2 latency (ms, by counter) |
| --- | --- | --- | --- | --- |
| esp32c3 / control-gtk-v1 | 3/3 | `[]` | `[]` / `[]` | `{'3': 12.543, '4': 52.29, '5': 10.127}` |
| esp32c3 / source-gtk-v1 | 3/3 | `[]` | `[42]` / `[]` | `{'3': 20.754, '4': 13.688, '5': 14.541}` |
| esp32s3 / control-gtk-v1 | 3/3 | `[]` | `[]` / `[]` | `{'3': 17.988, '4': 17.713, '5': 25.782}` |
| esp32s3 / source-gtk-v1 | 3/3 | `[]` | `[62]` / `[]` | `{'3': 31.906, '5': 16.347, '6': 18.986}` |

- `esp32c3/source-gtk-v1` misses broadcast sequence 42; present in `eth10`: `True`, `br0`: `True`. It is 699.637 ms after completed G2 counter 4; paired group capture separation is 0.11 ms.
- `esp32s3/source-gtk-v1` misses broadcast sequence 62; present in `eth10`: `True`, `br0`: `True`. It is 681.262 ms after completed G2 counter 6; paired group capture separation is 0.117 ms.
- `esp32s3/source-gtk-v1`: G1 counters without captured G2: `[4]`. Request intervals and key-installation results remain in the numeric report.
- `esp32s3/source-gtk-v1`: same-key updates without reinstallation: `[{'counter': 5, 'key_id': 2, 'installed': False, 'protected': True}]`. Completion is checked per requested interval, separately from the raw reader's legacy exactly-three-update flag.

In the S3 source trial, the device reports success for the G2 reply to counter
4, but that reply is absent from both AP captures. The AP retries with counter
5; the device replies without reinstalling the same key (`installed=false`),
and the AP captures that reply. All three request intervals eventually
complete. The raw reader's legacy exactly-three-update flag is false because
there are four updates; the report preserves it alongside the three actual
installations, the retry and the completed intervals.

AP Ethernet observations do not locate RF/device losses or prove their cause.
A reported MAC success is not proof of AP acceptance. Historical packet gaps
and timing tails remain open, including the [feature comparison](PHY-FEATURE-VALIDATION.md)
and [basic comparison](PHY-BASIC-VALIDATION.md). Successful traffic here does
not establish that removing this member fixes those observations or proves
long-duration reliability.

## Restoration and remaining work

Both boards were restored to ordinary source station images and passed two
additional connections each. Every flash checked forced chip identity and
security state; S3 app images were signed and verified with the existing key.
Only existing application slots were written. Owned router workers and
temporary files were removed; monitor mode remains zero and persistent AP
configuration is unchanged. C3 finished disconnected; the final paired
flasher holds S3 in ROM. Both retain ordinary source application images.

Eleven vendor PHY members remain: power detection, analog calibration,
tracking, TX gain, PLL, RX gain, register programming, frequency control, RF
initialization, TX calibration and RX calibration. Vendor state and ROM
callbacks remain. This milestone covers one board per chip, one AP and short
trials. Calibrated RF/voltage accuracy, other temperatures, sleep/coexistence
and long-duration reliability remain unvalidated.
