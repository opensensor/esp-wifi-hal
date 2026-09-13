# PHY API member: C3/S3 source and device comparison

The [Rust PHY API implementation](PHY-API.md), commit `c640388`, removes every
allocated `phy_api.o` input in the compared images. Control `2c55995` retains
the original API member and all earlier MAC/PHY replacements. Both sides use
the same expanded lifetime probe. The [numeric report](phy-api-validation.json)
records build hashes, allocation gates, native code and actual traffic counts.

FoA remains `c433109960bc2b346a45da47c2bd3d2cb32690bf`, including the
[EAPOL completion correction](EAPOL-TX-COMPLETION.md), and sys remains
`73add8985cec3b7582e6df80a4273022deb844b0`. All sixteen builds use the same
committed dependency lock. Recorded source hashes were checked against the
implementation commit; the control's identical lifetime-probe overlay is
recorded explicitly. Both sides use 80 MHz, quiet timing logs and unchanged
RF tracking cadence. Original vendor archives are unchanged.

## Linked ownership and instructions

| Chip | Control vendor PHY bytes | Source vendor PHY bytes | Removed API bytes | PHY members |
| --- | ---: | ---: | ---: | --- |
| esp32c3 | 31,377 | 31,203 | 174 | 15 → 14 |
| esp32s3 | 29,618 | 29,483 | 147 | 15 → 14 |

These are allocated non-string vendor inputs, not whole-image savings. Rust
source bodies also occupy memory. S3's retained `phy_init.o` IRAM allocation
increases by twelve bytes: three four-byte literals for `g_phyFuns`, `phy_param`
and `__opensensor_tsens_power` previously shared storage in `phy_api.o`.
Both retained wakeup/close instruction streams match after resolving literal
values and relocating branches/calls; their sizes remain 344 and 87 bytes.
Thus S3 removes 147 API bytes but reduces total vendor inputs by 135 bytes.
Its GTK totals are eight bytes smaller on each side, 29,610 → 29,475.
No other retained input changes size. C3 removes exactly 174 bytes.

All eight full station/GTK allocation gates pass, retaining earlier formatter,
wrapper, dispatcher, temperature, sensor, PBUS and I2C checks and no allocated
`libpp.a`. Eight reduced lifetime/RX profiles separately pass API ownership,
retained-helper and absent-member checks; they are not described as full
station audits. The member is absent even though its previously superseded
sensor body shared a coarse IRAM input in the control.

Production matches **226,594 original-instruction cases at O0 and O2**:
94,721 C3 and 131,873 S3. Twelve focused oracle tests and all 110 allocation
regressions pass normally and with Python assertions disabled. ESP32 and S2
compatibility builds pass; those chips were not tested on hardware here.

Native review covers 28 exported source bodies across the four source profiles
per chip, checking aliases, entry placement and required S3 IRAM literals.
Wakeup and close entries are in IRAM; the version getter and S3 seed helper
remain in flash. S3 seed uses masks 127 and -128 with one ordered 32-bit MMIO
read/write and barriers. Volatile parameter/table accesses can add barriers
and change instruction counts; this is not cycle-equivalence evidence.
The retained flash calls in wakeup/measurement do not establish transitive
flash independence.

## Lifecycle, callbacks and RX

All four lifetime trials complete three full PHY guard cycles, nonempty
calibration, sensor shutdown checks, six PBUS range checks and the existing
live I2C callback installation checks. API flags read `0x1ddde20` in every
observed cycle, with version 1232 on C3 and 711 on S3. Recorded wakeup/close
addresses match the selected ELF symbols; source addresses match Rust bodies.
Every C3 release records close byte one at `+0x320`.

The observed wakeup gate is already set: these live runs do not demonstrate
the conditional frequency/channel fallback branch. That branch, helper state
mutations and arbitrary seed bit patterns are covered by the instruction
oracle. The probe issues no extra RF operation and does not directly exercise
all TX-seed inputs or measure analog behavior.

| Chip | Implementation | I2C slot checks | Beacons after wakeup | RX frames / OFDM |
| --- | --- | ---: | ---: | --- |
| esp32c3 | control | 12 | 2 | 6 / 2 |
| esp32c3 | source | 12 | 3 | 10 / 2 |
| esp32s3 | control | 15 | 2 | 10 / 2 |
| esp32s3 | source | 15 | 2 | 9 / 3 |

All four RX probes preserve pending buffers, recover from exhaustion and
transmit OFDM. Temperature values are recorded, but sequential trials without
controlled thermal conditions do not establish temperature accuracy.

## Traffic and key rotation

Ordinary and restored-source trials each make two connections. Each GTK trial
makes one connection, sends 300 router echoes with 512-byte payloads and twenty
gateway echoes, and sends 120 broadcasts plus 120 multicasts with 128-byte
payloads while requesting three group-key rotations.

| Chip | Trial | Router echoes | Gateway echoes | Broadcast | Multicast | Median / maximum router RTT (ms) |
| --- | --- | --- | --- | --- | --- | --- |
| esp32c3 | control-normal-v1 | 40/40 | 40/40 | — | — | 11.790 / 84.679 |
| esp32c3 | source-normal-v1 | 40/40 | 40/40 | — | — | 6.876 / 104.266 |
| esp32c3 | control-gtk-v1 | 300/300 | 20/20 | 119/120 | 120/120 | 11.648 / 154.185 |
| esp32c3 | source-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 13.101 / 201.312 |
| esp32c3 | source-restored-v1 | 40/40 | 40/40 | — | — | 3.993 / 85.990 |
| esp32s3 | control-normal-v1 | 40/40 | 40/40 | — | — | 9.197 / 49.219 |
| esp32s3 | source-normal-v1 | 40/40 | 40/40 | — | — | 11.495 / 80.791 |
| esp32s3 | control-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 6.207 / 81.794 |
| esp32s3 | source-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 6.787 / 120.515 |
| esp32s3 | source-restored-v1 | 40/40 | 40/40 | — | — | 7.271 / 79.198 |

All four GTK trials record three station requests and matching G1/G2 exchanges.
A separate raw-pcap reader corroborates all 320 echo payload pairs per trial,
group sequences and EAPOL counters. `eth10` captures both EAPOL directions;
`br0` corroborates station requests/replies but does not capture AP-originated
G1. All capture workers report zero drops, truncation and missing timestamps.

- `esp32c3/control-gtk-v1`: G1-to-G2 latency in ms `{'3': 13.889, '4': 20.306, '5': 35.696}`; missing group sequences `{'broadcast': [67], 'multicast': []}`.
- `esp32c3/source-gtk-v1`: G1-to-G2 latency in ms `{'3': 12.745, '4': 10.302, '5': 38.15}`; missing group sequences `{'broadcast': [], 'multicast': []}`.
- `esp32s3/control-gtk-v1`: G1-to-G2 latency in ms `{'3': 22.832, '5': 11.262, '6': 17.584}`; missing group sequences `{'broadcast': [], 'multicast': []}`.
- `esp32s3/source-gtk-v1`: G1-to-G2 latency in ms `{'3': 26.483, '4': 21.763, '5': 30.976}`; missing group sequences `{'broadcast': [], 'multicast': []}`.

C3 control loses broadcast sequence 67 despite its presence in both AP
captures. It occurs 3,190.551 ms after completed G2 counter 5. The paired
multicast is captured 0.096 ms apart and reaches the device. The gap remains
unexplained; these Ethernet observations cannot locate the RF/device loss.
The original trial is preserved.

S3 control reports a successful reply to G1 counter 4, but G2 counter 4 is
absent from both AP captures. The AP sends counter 5 for the same key; the
device reports `installed=false`, replies, and completes that rotation without
reinstallation. All three request intervals complete, with four G1 messages
and three captured G2 replies. The report preserves the missing first reply;
its successful completion indication does not prove AP reception. The older
raw reader's strict three-update summary is false for this retry; the report
instead checks each request interval and counts actual key installations.

Successful source traffic does not prove the API replacement fixes either
observation or the historical timing/packet losses.

## Restoration and remaining work

Both boards were restored to ordinary source station images and passed two
additional connections each, as recorded above. Every flash checked forced
chip identity and security state; S3 app images were signed and verified with
the existing key. Only existing application slots were written. Owned router
workers and temporary files were removed; monitor mode remains zero and
persistent AP configuration is unchanged.

Fourteen vendor PHY members remain, including RF/channel initialization,
frequency selection, PLL, RX/TX calibration, power detection/gain and tracking,
plus vendor state and ROM callbacks. This milestone removes one allocated
member, not the whole PHY. It covers one board per chip, one AP and these
short trials; calibrated RF measurements, other temperatures, sleep/coexistence
and long-duration reliability remain unvalidated.
