# PHY RC calibration: C3/S3 source and device comparison

The [Rust implementation](PHY-ANALOG.md), commit
`2dca8f3e0e8e781d25894739bb9d6b0d29799db9`, removes every allocated `phy_analog_cal.o`
input in the compared images. Control `22d2066` retains the original analog
member and all earlier MAC/PHY replacements. Both sides use the same expanded
lifetime probe. The [numeric report](phy-analog-validation.json) records
source/build hashes, linked ownership, native checks and actual traffic.

FoA remains `c433109960bc2b346a45da47c2bd3d2cb32690bf`, including the
[EAPOL completion correction](EAPOL-TX-COMPLETION.md); sys remains
`73add8985cec3b7582e6df80a4273022deb844b0`. All sixteen builds use the committed
dependency lock. Every recorded source hash matches the implementation or
control commit with the explicit common probe overlay. Both sides use 80 MHz,
quiet timing logs and unchanged RF tracking cadence. Vendor archives are
unchanged.

## Linked ownership and instruction behavior

| Chip | Control vendor PHY bytes | Source vendor PHY bytes | Removed analog member bytes | PHY members |
| --- | ---: | ---: | ---: | --- |
| esp32c3 | 29,141 | 28,400 | 741 | 10 → 9 |
| esp32s3 | 27,898 | 27,245 | 649 | 10 → 9 |

S3 GTK totals are 27,890 → 27,237; C3 totals are unchanged between ordinary
and GTK profiles. S3's decrease includes four additional bytes in retained
`phy_rx_cal.o`: the linker shares the `0xfff80000` literal used by
`rfrx_sat_rst`. Its 91-byte body has identical instructions after resolving
literal values and branch offsets. The owned input shrinks from 111 to 107
bytes. No other retained input changes identity or size. These are allocated
non-string vendor inputs, not whole-image savings; Rust code and data also
occupy memory.

All eight full station/GTK allocation audits pass, composing earlier
formatter, wrapper, dispatcher, temperature, lifecycle, PBUS, I2C, API, basic,
feature, debug and power-detector gates. No prior ownership exception was
needed. Every analog member input must be absent, including literals,
data and mergeable strings. C3 writable divisor objects and aliases are
checked for size, alignment, initialization, containment and overlap. S3
rejects those C3 globals. No `libpp.a` input is allocated. Eight reduced
lifetime/RX profiles separately pass the analog ownership and earlier
absent-member checks; those are not full station audits.

Production matches **541,656 original-instruction cases at O0 and O2**:
336,364 C3 and 205,292 S3 cases. Twenty-five focused oracle tests and all
187 allocation regressions pass normally and with Python assertions disabled.
ESP32 and S2 compatibility builds pass; neither was tested on hardware.
The public extractor reproduces both pinned instruction fixtures exactly.

Coverage includes separate exhaustive 16-bit selector/sample axes, C3's
independent exhaustive 16-bit divisor axes including zero, wrapping signed
arithmetic, low-halfword narrowing before clamping, callback-table reloads,
state mutations, nested measurement and raw 64-bit ROM return transport.
It is not the full Cartesian input domain. The model keeps ROM arithmetic
opaque, using finite numeric examples and injected return words to check
its boundary. It does not prove the ROM implementation's numerical accuracy.

Native instruction checks cover two emitted source functions in each of
four profiles per chip: sixteen bodies, with 340 diagnostic cases per profile
(2,720 profile-case executions). All boundary traces match the original
model, including parameter accesses, callback calls, delay, soft-double
arguments and returns. C3 compiler-generated selector tables are read only
through identified `.rodata` input ranges, even when the output section is
writable RAM. Native cases supplement the larger host corpus. Both source
entries remain in flash; C3 divisors remain writable RAM. Stack layouts,
instruction counts and barriers differ. This is not cycle or analog
equivalence.

## Calibration, lifetime and RX probes

All four lifetime trials complete three PHY guard cycles, nonempty
calibration, sensor shutdown and previous probes. The new stage observes the
normal RC measurement and eight coefficient bytes, checks the completion bit
and coefficient bounds, then confirms that calling the already-calibrated
entry leaves flags and all nine bytes unchanged. It adds no extra measurement
or analog programming. The normal initialization path performs calibration.

| Chip | Implementation | Stable early-return cycles | Initial measurement / eight coefficients | Beacons after wakeup | RX frames / OFDM |
| --- | --- | ---: | --- | ---: | --- |
| esp32c3 | control | 3 | `[43, 34, 34, 11, 11, 23, 18, 44, 18]` | 2 | 11 / 2 |
| esp32c3 | source | 3 | `[42, 34, 34, 11, 11, 22, 17, 43, 17]` | 2 | 8 / 2 |
| esp32s3 | control | 3 | `[38, 32, 32, 10, 10, 21, 16, 31, 16]` | 2 | 11 / 3 |
| esp32s3 | source | 3 | `[39, 33, 33, 11, 11, 21, 16, 31, 16]` | 2 | 8 / 1 |

Every observed entry agrees with its ELF; source entries agree with the strong
aliases. C3 retains divisor values 155 and 355. The installed masked read/write
callbacks remain ROM: C3 `0x400391f4`/`0x4003922a`, S3
`0x4003589c`/`0x400358d8`. They are observed on all three cycles. This does
not replace those ROM bodies or establish analog accuracy.

All four RX probes preserve pending buffers, recover from exhaustion and
transmit OFDM. Earlier temperature, sensor, PBUS, I2C, API, basic, feature,
debug and power-detector observations remain in the numeric report, along
with the retained power-detector ROM buffer evidence.

## Traffic and key rotation

Ordinary and restored-source trials each make two connections. Each GTK trial
makes one connection, sends 300 router echoes with 512-byte payloads and twenty
gateway echoes, and sends 120 broadcasts plus 120 multicasts with 128-byte
payloads while requesting three group-key rotations.

| Chip | Trial | Router echoes | Gateway echoes | Broadcast | Multicast | Median / maximum router RTT (ms) |
| --- | --- | --- | --- | --- | --- | --- |
| esp32c3 | control-normal-v1 | 40/40 | 40/40 | — | — | 8.386 / 67.351 |
| esp32c3 | source-normal-v1 | 40/40 | 40/40 | — | — | 10.100 / 87.271 |
| esp32c3 | control-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 7.612 / 224.043 |
| esp32c3 | source-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 10.322 / 149.326 |
| esp32c3 | source-restored-v1 | 40/40 | 40/40 | — | — | 6.779 / 148.925 |
| esp32s3 | control-normal-v1 | 40/40 | 40/40 | — | — | 8.588 / 88.215 |
| esp32s3 | source-normal-v1 | 40/40 | 40/40 | — | — | 2.634 / 88.933 |
| esp32s3 | control-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 6.546 / 161.017 |
| esp32s3 | source-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 7.332 / 122.039 |
| esp32s3 | source-restored-v1 | 40/40 | 40/40 | — | — | 5.048 / 78.144 |

A separate raw-pcap reader corroborates echo payload pairs, group sequences
and EAPOL counters. `eth10` captures both EAPOL directions; `br0` corroborates
station requests/replies but does not capture AP-originated G1. All capture
workers report zero drops, truncation and missing timestamps. Every completed
trial is retained, including packet gaps or incomplete rotations.

| Chip / GTK trial | Completed rotations / requested | Request counters absent at AP | Missing broadcast / multicast sequences | G1-to-G2 latency (ms, by counter) |
| --- | --- | --- | --- | --- |
| esp32c3 / control-gtk-v1 | 3/3 | `[]` | `[]` / `[]` | `{'3': 30.507, '4': 18.398, '5': 77.69}` |
| esp32c3 / source-gtk-v1 | 3/3 | `[]` | `[]` / `[]` | `{'3': 18.513, '4': 14.924, '5': 27.143}` |
| esp32s3 / control-gtk-v1 | 3/3 | `[]` | `[]` / `[]` | `{'3': 28.588, '4': 18.536, '5': 17.808}` |
| esp32s3 / source-gtk-v1 | 3/3 | `[]` | `[]` / `[]` | `{'3': 70.415, '4': 41.037, '5': 20.468}` |


## Cumulative timing observations

| Chip / GTK trial | PHY maximum (us) | Console maximum (us) | TX resume maximum (us) | RX age maximum (us) |
| --- | ---: | ---: | ---: | ---: |
| esp32c3 / control-gtk-v1 | 86 | 1931 | 1557 | 8201 |
| esp32c3 / source-gtk-v1 | 84 | 1808 | 1785 | 8524 |
| esp32s3 / control-gtk-v1 | 91 | 4025 | 2975 | 8510 |
| esp32s3 / source-gtk-v1 | 87 | 4468 | 1438 | 8412 |

These are cumulative maxima, not per-packet correlations. Console and RX-age tails remain visible even in these runs with no missing test packets.

AP Ethernet observations do not locate RF/device losses or prove their cause.
A reported MAC success is not proof of AP acceptance. Historical packet gaps
and latency tails remain open, including the [power-detector comparison](PHY-PWDET-VALIDATION.md).
Successful traffic here does not establish that replacing this member fixes
those observations or proves long-duration reliability.

## Restoration and remaining work

Both boards were restored to ordinary source station images and passed two
additional connections each. Every flash checked forced chip identity and
security state; S3 app images were signed and verified with the existing key.
Only existing application slots were written. Owned router workers and
temporary files were removed; monitor mode remains zero and persistent AP
configuration is unchanged. C3 finished disconnected; the final paired
flasher holds S3 in ROM. Both retain ordinary source application images.

Nine allocated vendor PHY members remain: tracking, TX gain, PLL, RX gain,
register programming, frequency control, RF initialization, TX calibration
and RX calibration. Vendor state, ROM analog access, soft-double arithmetic
and earlier opaque ROM dependencies remain. This milestone covers one board
per chip, one AP and short trials. Calibrated RF/power accuracy, other
temperatures, sleep/coexistence and long-duration reliability remain
unvalidated.

All sixteen planned device trials and both restoration trials completed on their first recorded attempt.
