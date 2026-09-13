# Basic PHY member: C3/S3 source and device comparison

The [Rust basic PHY implementation](PHY-BASIC.md), commit
`274c81027ceb9e6855386858306db04e1461002f`, removes every allocated `phy_basic.o` input
in the compared images. Control `789c26f` retains the original basic member
and all earlier MAC/PHY replacements. Both sides use the same expanded
lifetime probe. The [numeric report](phy-basic-validation.json) records
build hashes, allocation gates, native review and actual traffic counts.

FoA remains `c433109960bc2b346a45da47c2bd3d2cb32690bf`, including the
[EAPOL completion correction](EAPOL-TX-COMPLETION.md), and sys remains
`73add8985cec3b7582e6df80a4273022deb844b0`. All sixteen builds use the committed
dependency lock. Every recorded source hash was checked against the
implementation commit or control with the explicit identical probe overlay.
Both sides use 80 MHz, quiet timing logs and unchanged RF tracking cadence.
Original vendor archives are unchanged.

## Linked ownership and instructions

| Chip | Control vendor PHY bytes | Source vendor PHY bytes | Removed basic bytes | PHY members |
| --- | ---: | ---: | ---: | --- |
| esp32c3 | 31,203 | 30,877 | 328 | 14 → 13 |
| esp32s3 | 29,483 | 29,092 | 399 | 14 → 13 |

These are allocated non-string vendor inputs, not whole-image savings; the
Rust bodies also occupy memory. C3 removes 328 basic-member bytes but its
retained `chip_v7_set_chan` call to channel-14 configuration widens from two
to four bytes. Its vendor-input reduction is therefore 326 bytes.

S3 removes 399 basic-member bytes, while `phy_reg.o` gains two four-byte
literals formerly shared with basic: reset bit `0x04000000` in its IRAM input
and division multiplier `0x66666667` in `.text.phy_freq_correct`. Retained
function sizes in those inputs stay unchanged. The net vendor reduction is
391 bytes. S3 GTK totals are eight bytes smaller on each side:
29,475 → 29,084. Every other retained input keeps its size. Native review
checks these explanations in both ordinary and GTK profiles.

All eight full station/GTK allocation gates pass, composing all earlier
formatter, wrapper, dispatcher, temperature, sensor, PBUS, I2C and API gates.
No `libpp.a` input is allocated. Eight reduced lifetime/RX profiles separately
pass basic ownership, retained-helper and absent-member checks; these are
not described as full station audits. `rom_set_chan_reg` remains absolute
ROM at `0x40001bec` on C3 and `0x4000633c` on S3. A stale S3 symbol size does
not turn the ROM alias into an allocated archive body.

Production matches **841,856 original-instruction cases at O0 and O2**:
27,072 C3 and 814,784 S3. Fifteen focused oracle tests and all 125 allocation
regressions pass normally and with Python assertions disabled. ESP32 and S2
compatibility builds pass; those chips were not tested on hardware here.

Native review covers twenty source bodies across four profiles per chip.
Reset entries and required S3 literals are in IRAM; channel-14 configuration
and S3 interpolation stay in flash. The reset loop and volatile accesses can
change instruction counts and add barriers. Ordered modeled behavior is not
cycle, analog or calibrated RF equivalence.

## Lifecycle, callbacks and RX

All four lifetime trials complete three full PHY guard cycles, nonempty
calibration, sensor shutdown, six PBUS range checks, live I2C callback checks
and the prior API checks. Selected reset/channel/interpolation addresses
match the ELF; source addresses match Rust bodies and ROM routing is retained.
S3 also passes seven pure interpolation vectors per guard, 21 per trial.
The probe does not force an extra reset, channel-14 operation or AP channel
change; host coverage of those branches does not establish channel-14 RF
behavior. Calibration cadence stays unchanged.

| Chip | Implementation | I2C slot checks | Beacons after wakeup | RX frames / OFDM |
| --- | --- | ---: | ---: | --- |
| esp32c3 | control | 12 | 2 | 7 / 2 |
| esp32c3 | source | 12 | 2 | 12 / 3 |
| esp32s3 | control | 15 | 2 | 7 / 1 |
| esp32s3 | source | 15 | 2 | 7 / 2 |

All four RX probes preserve pending buffers, recover from exhaustion and
transmit OFDM. Temperature measurements are retained without claiming
accuracy from sequential trials in uncontrolled thermal conditions.

## Traffic and key rotation

Ordinary and restored-source trials each make two connections. Each GTK trial
makes one connection, sends 300 router echoes with 512-byte payloads and twenty
gateway echoes, and sends 120 broadcasts plus 120 multicasts with 128-byte
payloads while requesting three group-key rotations.

| Chip | Trial | Router echoes | Gateway echoes | Broadcast | Multicast | Median / maximum router RTT (ms) |
| --- | --- | --- | --- | --- | --- | --- |
| esp32c3 | control-normal-v1 | 40/40 | 40/40 | — | — | 7.397 / 51.801 |
| esp32c3 | source-normal-v1 | 40/40 | 40/40 | — | — | 13.419 / 30.910 |
| esp32c3 | control-gtk-v1 | 300/300 | 20/20 | 119/120 | 120/120 | 12.164 / 114.715 |
| esp32c3 | source-gtk-v1 | 300/300 | 20/20 | 119/120 | 120/120 | 10.021 / 100.529 |
| esp32c3 | source-restored-v1 | 40/40 | 40/40 | — | — | 11.079 / 186.775 |
| esp32s3 | control-normal-v1 | 40/40 | 40/40 | — | — | 4.889 / 90.592 |
| esp32s3 | source-normal-v1 | 40/40 | 40/40 | — | — | 11.062 / 76.008 |
| esp32s3 | control-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 7.080 / 68.611 |
| esp32s3 | source-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 4.516 / 125.441 |
| esp32s3 | source-restored-v1 | 40/40 | 40/40 | — | — | 11.370 / 91.703 |

A separate raw-pcap reader corroborates all 320 echo payload pairs per GTK
trial, group sequences and EAPOL counters. `eth10` captures both EAPOL
directions; `br0` corroborates station requests/replies but does not capture
AP-originated G1. All capture workers report zero drops, truncation and
missing timestamps. Completed trials are preserved, including packet gaps
and incomplete requested rotations.

| Chip / GTK trial | Completed rotations / requested | Request counters absent at AP | Missing broadcast / multicast sequences | G1-to-G2 latency (ms, by counter) |
| --- | --- | --- | --- | --- |
| esp32c3 / control-gtk-v1 | 3/3 | `[]` | `[41]` / `[]` | `{'3': 26.932, '4': 19.146, '5': 20.815}` |
| esp32c3 / source-gtk-v1 | 2/3 | `[0]` | `[41]` / `[]` | `{'3': 18.21, '4': 31.174}` |
| esp32s3 / control-gtk-v1 | 3/3 | `[]` | `[]` / `[]` | `{'3': 26.17, '4': 35.799, '5': 36.065}` |
| esp32s3 / source-gtk-v1 | 3/3 | `[]` | `[]` / `[]` | `{'3': 25.608, '4': 58.619, '5': 46.647}` |

Both C3 trials miss broadcast sequence 41 despite its presence in both AP
captures. It occurs 241.023 ms after completed G2 counter 4 in control and
222.593 ms after completed G2 counter 3 in source. Each paired multicast is
captured within 0.1 ms and reaches the device. The timing correlation warrants
further investigation but these Ethernet observations cannot locate the
RF/device loss or establish its cause.

C3 source also reports `Ok(())` for its first request (wire replay counter 0),
which is absent from both AP captures. Its window contains one event-8 record,
`phase=10 outcome=0`, with zero overwritten records. Outcome zero reports MAC
success; this is not evidence of the missing-completion/`None` path fixed in
FoA. The bounded window does not uniquely identify every concurrent frame.
The other two captured requests complete their G1/G2 exchanges, so this trial
validates **two completed rotations out of three requested**, not three.
Successful MAC completion does not establish AP acceptance.

The numeric report checks each captured request interval and records the
missing counters explicitly. It preserves the older reader's strict
three-update summary without treating that summary as a universal success
gate. Historical packet gaps and timing tails remain open; this PHY
replacement is not presented as their fix.

## Restoration and remaining work

Both boards were restored to ordinary source station images and passed two
additional connections each. Every flash checked forced chip identity and
security state; S3 app images were signed and verified with the existing key.
Only the existing application slots were written. Owned router workers and
temporary files were removed; monitor mode remains zero and persistent AP
configuration is unchanged. C3 finished disconnected, and the final paired
flasher holds S3 in ROM; both retain ordinary source application images.

Thirteen vendor PHY members remain: debug, power detection, analog calibration,
feature/power helpers, tracking, TX gain, PLL, RX gain, register programming,
frequency control, RF initialization, TX calibration and RX calibration.
Vendor state and ROM callbacks remain. This milestone covers one board per
chip, one AP and short trials; other temperatures, calibrated RF measurements,
sleep/coexistence and long-duration reliability remain unvalidated.
