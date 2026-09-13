# PHY feature member: C3/S3 source and device comparison

The [Rust feature implementation](PHY-FEATURE.md), commit
`9cca50a9508d45121beee7dacb7409762c45a044`, removes every allocated `phy_feature.o` input
in the compared images. Control `50d5e44` retains the original feature member
and all earlier MAC/PHY replacements. Both sides use the same expanded lifetime
probe. The [numeric report](phy-feature-validation.json) records build hashes,
allocation gates, native review and actual traffic results.

FoA remains `c433109960bc2b346a45da47c2bd3d2cb32690bf`, including the
[EAPOL completion correction](EAPOL-TX-COMPLETION.md), and sys remains
`73add8985cec3b7582e6df80a4273022deb844b0`. All sixteen builds use the committed
dependency lock. Every recorded source hash was checked against the
implementation commit or control with the explicit identical probe overlay.
Both sides use 80 MHz, quiet timing logs and unchanged RF tracking cadence.
Original vendor archives are unchanged.

## Linked ownership and instructions

| Chip | Control vendor PHY bytes | Source vendor PHY bytes | Removed feature bytes | PHY members |
| --- | ---: | ---: | ---: | --- |
| esp32c3 | 30,877 | 30,101 | 764 | 13 → 12 |
| esp32s3 | 29,092 | 28,582 | 510 | 13 → 12 |

These are allocated non-string vendor inputs, not whole-image savings; the
Rust bodies also occupy memory. C3 removes 764 feature bytes and saves another
twelve bytes through linker relaxation: six retained `jal` instructions shrink
from four bytes to two. Two calls are in `ram1_phy_wakeup_init`, three in
`get_rf_freq_init`, and one in `set_channel_rfpll_freq`. Their opcode sequences
and resolved callee names are preserved. Both ordinary and GTK profiles were
checked. S3 removes exactly 510 bytes; GTK totals are 29,084 → 28,574.
Every other retained input keeps its size.

C3's removed member includes 256 bytes of residual register save/restore code
inside a coarse IRAM input. Counting just its four named live helpers would
miss that storage. The ROM backup bindings stay absolute: C3 digital
`0x40001c30`, frequency `0x40001c20`; S3 digital `0x40006408`, frequency
`0x400063d8`. Stale S3 ROM symbol sizes do not establish allocated bodies.

All eight full station/GTK audits pass, composing earlier formatter, wrapper,
dispatcher, temperature, sensor, PBUS, I2C, API and basic gates. The explicit
feature stage replaces two former retained boundaries: the lifecycle gate's
digital backup wrapper and the basic gate's power helper. Each requires a real
source body, correct alias and no vendor overlap; digital backup must remain
in IRAM. Earlier standalone audits retain their original ownership rules.
No `libpp.a` input is allocated. Eight reduced lifetime/RX profiles separately
pass feature ownership, retained-helper and absent-member checks; these are
not described as full station audits.

Production matches **414,480 original-instruction cases at O0 and O2**:
207,240 per chip. Sixteen focused oracle tests and all 147 allocation regressions
pass normally and with Python assertions disabled. ESP32 and S2 compatibility
builds pass; those chips were not tested on hardware here.

Native review covers 32 source bodies across four profiles per chip. Backup
entries and required S3 ROM literals stay in IRAM. Power and channel-mode
helpers remain in flash. C3 still calls its retained gain helper; S3 preserves
the gain callback slot. The source uses volatile state accesses and a loop for
the eight analog writes; barriers, stack usage and instruction counts differ
from the original unrolled code. This is not cycle or analog equivalence.

## Lifetime and RX probes

All four lifetime trials complete three full PHY guard cycles, nonempty
calibration, sensor shutdown, six PBUS range checks, I2C callback checks and
the earlier API/basic probes. The feature stage records selected entry and
ROM addresses plus existing power/mode bytes. Guard release/wakeup exercises
the existing backup flow. The probe issues no extra power/channel-mode
operation or RF cadence change; host branch coverage does not establish RF
behavior in unusual channel modes.

| Chip | Implementation | Power byte / enabled / narrow (each cycle) | I2C slot checks | Beacons after wakeup | RX frames / OFDM |
| --- | --- | --- | ---: | ---: | --- |
| esp32c3 | control | `[(100, 0, 0), (100, 0, 0), (100, 0, 0)]` | 12 | 2 | 9 / 1 |
| esp32c3 | source | `[(100, 0, 0), (100, 0, 0), (100, 0, 0)]` | 12 | 2 | 7 / 2 |
| esp32s3 | control | `[(100, 0, 0), (100, 0, 0), (100, 0, 0)]` | 15 | 2 | 11 / 2 |
| esp32s3 | source | `[(100, 0, 0), (100, 0, 0), (100, 0, 0)]` | 15 | 2 | 11 / 1 |

All four RX probes preserve pending buffers, recover from exhaustion and
transmit OFDM. Temperature observations are retained without claiming
accuracy from sequential trials in uncontrolled thermal conditions.

## Traffic and key rotation

Ordinary and restored-source trials each make two connections. Each GTK trial
makes one connection, sends 300 router echoes with 512-byte payloads and twenty
gateway echoes, and sends 120 broadcasts plus 120 multicasts with 128-byte
payloads while requesting three group-key rotations.

| Chip | Trial | Router echoes | Gateway echoes | Broadcast | Multicast | Median / maximum router RTT (ms) |
| --- | --- | --- | --- | --- | --- | --- |
| esp32c3 | control-normal-v1 | 40/40 | 40/40 | — | — | 7.468 / 69.020 |
| esp32c3 | source-normal-v1 | 40/40 | 40/40 | — | — | 5.169 / 135.791 |
| esp32c3 | control-gtk-v1 | 300/300 | 20/20 | 119/120 | 120/120 | 6.109 / 146.482 |
| esp32c3 | source-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 12.777 / 87.576 |
| esp32c3 | source-restored-v1 | 40/40 | 40/40 | — | — | 4.454 / 50.543 |
| esp32s3 | control-normal-v1 | 40/40 | 40/40 | — | — | 6.200 / 58.248 |
| esp32s3 | source-normal-v1 | 40/40 | 40/40 | — | — | 5.097 / 118.592 |
| esp32s3 | control-gtk-v1 | 300/300 | 20/20 | 118/120 | 120/120 | 10.790 / 481.101 |
| esp32s3 | source-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 10.013 / 120.191 |
| esp32s3 | source-restored-v1 | 40/40 | 40/40 | — | — | 4.530 / 88.752 |

A separate raw-pcap reader corroborates echo payload pairs, group sequences
and EAPOL counters. `eth10` captures both EAPOL directions; `br0` corroborates
station requests/replies but does not capture AP-originated G1. All capture
workers report zero drops, truncation and missing timestamps. The report
retains every completed trial, including packet gaps or incomplete rotations.

| Chip / GTK trial | Completed rotations / requested | Request counters absent at AP | Missing broadcast / multicast sequences | G1-to-G2 latency (ms, by counter) |
| --- | --- | --- | --- | --- |
| esp32c3 / control-gtk-v1 | 3/3 | `[]` | `[31]` / `[]` | `{'3': 21.04, '5': 9.457, '6': 12.209}` |
| esp32c3 / source-gtk-v1 | 3/3 | `[]` | `[]` / `[]` | `{'3': 20.836, '4': 17.929, '5': 52.634}` |
| esp32s3 / control-gtk-v1 | 3/3 | `[]` | `[24, 61]` / `[]` | `{'3': 37.222, '4': 19.749, '5': 30.133}` |
| esp32s3 / source-gtk-v1 | 3/3 | `[]` | `[]` / `[]` | `{'3': 38.354, '4': 34.377, '5': 18.14}` |

- `esp32c3/control-gtk-v1` misses broadcast sequence 31; present in `eth10`: `True`, `br0`: `True`. It is 5215.01 ms after completed G2 counter 3; paired group capture separation is 0.1 ms.
- `esp32c3/control-gtk-v1`: G1 counters without captured G2: `[4]`. The numeric report retains request intervals, retries and key-installation results.
- `esp32s3/control-gtk-v1` misses broadcast sequence 24; present in `eth10`: `True`, `br0`: `True`. It is 1645.127 ms after completed G2 counter 3; paired group capture separation is 0.092 ms.
- `esp32s3/control-gtk-v1` misses broadcast sequence 61; present in `eth10`: `True`, `br0`: `True`. It is 130.867 ms after completed G2 counter 5; paired group capture separation is 0.085 ms.

In the C3 control trial, the reply to G1 counter 4 reports success on the
device but is absent from both AP captures. The AP retries with counter 5
about one second later. The device replies without reinstalling the same key
(`installed=false`), and that reply reaches the AP. All three requested
rotation intervals eventually complete. The capture reader's historical
exactly-three-updates flag is false because this trial has four updates;
the numeric report preserves that flag alongside the three completed
intervals and the explicit same-key retry.

These AP Ethernet observations do not locate RF/device losses or prove their
cause. A reported MAC success is not proof of AP acceptance. The report checks
each captured request interval, retains missing counters, and records actual
key installations separately from same-key retries.

Historical packet gaps and timing tails remain open, including the
[preceding basic-PHY comparison](PHY-BASIC-VALIDATION.md)'s C3 broadcast gaps
and first request absent at the AP despite a MAC-success window. Successful
traffic here is not evidence that replacing `phy_feature.o` fixes those
observations or establishes long-duration reliability.

## Restoration and remaining work

Both boards were restored to ordinary source station images and passed two
additional connections each. Every flash checked forced chip identity and
security state; S3 app images were signed and verified with the existing key.
Only existing application slots were written. Owned router workers and
temporary files were removed; monitor mode remains zero and persistent AP
configuration is unchanged. C3 finished disconnected, and the final paired
flasher holds S3 in ROM; both retain ordinary source application images.

Twelve vendor PHY members remain: debug, power detection, analog calibration,
tracking, TX gain, PLL, RX gain, register programming, frequency control, RF
initialization, TX calibration and RX calibration. Vendor state and ROM
callbacks remain. This milestone covers one board per chip, one AP and short
trials. Other temperatures, calibrated RF measurements, sleep/coexistence and
long-duration reliability remain unvalidated.
