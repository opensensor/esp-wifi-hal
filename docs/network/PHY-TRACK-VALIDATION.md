# PHY tracking: C3/S3 source and device comparison

Implementation `8f2f90d2a03f7fe1356b4d7ffa41618003759c57` replaces the entire allocated
`phy_track.o` member with [Rust](PHY-TRACK.md). Control `e1fc477` retains that
member and all earlier MAC/PHY source replacements. Both sides use the same
expanded lifetime probe, 80-MHz CPU and quiet timing logs. The dispatcher and
RF tracking period are unchanged. The [numeric report](phy-track-validation.json)
contains source/build hashes, linked ownership, native checks and traffic.

FoA remains `c433109960bc2b346a45da47c2bd3d2cb32690bf` and sys remains `73add8985cec3b7582e6df80a4273022deb844b0`.
All sixteen final builds use the committed lock and verified source hashes.
The control's only overlay is the identical lifetime probe. Earlier preflight
and superseded source builds were not flashed and are excluded from final
build totals; the report retains their diagnostics.

## Ownership and instruction checks

| Chip | Control vendor PHY bytes | Source vendor PHY bytes | Removed tracking input | PHY members |
| --- | ---: | ---: | ---: | --- |
| esp32c3 | 28,400 | 27,292 | 1,108 | 9 → 8 |
| esp32s3 | 27,245 | 26,393 | 860 | 9 → 8 |

S3 GTK allocations are 27,237 → 26,385; C3 totals are the same across
ordinary and GTK profiles. These are non-string vendor-input allocations,
not whole-firmware savings. Rust also occupies memory.

C3 retained inputs keep their identities and sizes. Four S3 retained inputs
change their literal-pool sizes: `rfpll_cap_correct`, `gen_rx_gain_table` and
`set_rx_gain_table` each grow four bytes, while `phy_get_romfunc_addr` shrinks
four bytes. All four function bodies retain their sizes and resolved
instructions. Referenced symbols, exact strings and the read-only RX gain
table agree after relocation. These eight net bytes explain why S3's vendor
total decreases by 852 bytes when the 860-byte tracking member disappears.
Every other retained input keeps its identity and size.

All eight full station/GTK audits compose earlier source-ownership gates.
The tracking gate rejects every allocated member input, including literals,
data and excluded mergeable strings. It verifies all seven C3/eight S3 entry
aliases against real source bodies. Eight reduced lifecycle/RX profiles pass
separate ownership checks. Earlier removed members, `libpp.a` and the prebuilt
formatter remain absent.

Production passes **483,238 original-instruction cases at O0 and O2**:
238,658 C3 and 244,580 S3. Thirty focused interpreter tests and all 199 PHY
allocation regressions pass normally and with Python assertions disabled.
The public runner passes, and both fixtures reproduce exactly from pinned
ELF/map inputs. ESP32/S2 compatibility checks pass; those chips were not
hardware-tested here.

Coverage includes full low-halfword axes, chip argument widths, signed
thresholds/narrowing, volatile access order, callback replacement and mutation,
logging, and nested helpers. Four persistent-busy cases compare a bounded
prefix without claiming completion or adding a production timeout. This is a
selected corpus, not an exhaustive machine-domain proof.

Native checks execute 476 C3 and 544 S3 cases in each of four source profiles:
**4,080 profile-case executions across 60 emitted function bodies**. All
modeled traces match the original, including callbacks, direct helpers,
parameter widths, optional debug arguments and busy polling. The S3 native
check exposed LTO inlining of temperature-to-power; the final implementation
uses its existing ABI alias to preserve that call boundary. Source entries
remain in flash. Stack layouts, instructions and barriers differ; these checks
do not prove cycle timing or RF/analog equivalence.

## Lifetime and receive probes

All four lifetime trials complete three guard cycles, nonempty calibration,
sensor shutdown and previous probes. The new probe records every tracking
entry and relevant callback slot, reads normal temperature/ULP/offset state,
and checks unchanged flags and packed voltage state after calling only the
already-completed offset path. No additional PLL, ULP or power adjustment is
scheduled. In these room-temperature observations ULP base/current remain
zero; active ULP branches are covered by models, not demonstrated on-device.

| Chip | Implementation | Completed offset checks | First current / previous temperature | Packed offset word | Beacons after wakeup | RX frames / OFDM |
| --- | --- | ---: | --- | --- | ---: | --- |
| esp32c3 | control | 3 | 29 / 29 | `0xd4f0000` | 2 | 7 / 2 |
| esp32c3 | source | 3 | 28 / 28 | `0xd4f0000` | 2 | 7 / 2 |
| esp32s3 | control | 3 | 33 / 33 | `0xd770000` | 2 | 9 / 2 |
| esp32s3 | source | 3 | 33 / 33 | `0xd700000` | 2 | 10 / 2 |

Observed entry points and installed callbacks agree with their linked images.
Source entry points agree with the strong aliases; S3 power callback slot
`0x268` points to the new Rust implementation. ROM callbacks and wider
calibration/gain helpers remain. All four RX probes preserve pending buffers,
recover from exhaustion and transmit OFDM. Earlier sensor, PBUS, I2C, API,
basic, feature, debug, power-detector and analog-calibration observations are
retained in the numeric report.

## Traffic and key rotation

Ordinary and restored-source trials each make two connections. Each GTK trial
makes one connection, sends 300 router echoes with 512-byte payloads and twenty
gateway echoes, and sends 120 broadcasts plus 120 multicasts with 128-byte
payloads while requesting three group-key rotations.

| Chip | Trial | Router echoes | Gateway echoes | Broadcast | Multicast | Median / maximum router RTT (ms) |
| --- | --- | --- | --- | --- | --- | --- |
| esp32c3 | control-normal-v1 | 40/40 | 40/40 | — | — | 14.214 / 68.310 |
| esp32c3 | source-normal-v1 | 40/40 | 40/40 | — | — | 17.012 / 131.169 |
| esp32c3 | control-gtk-v1 | 300/300 | 20/20 | 119/120 | 120/120 | 30.794 / 201.976 |
| esp32c3 | source-gtk-v1 | 300/300 | 20/20 | 120/120 | 119/120 | 21.297 / 187.410 |
| esp32c3 | source-restored-v1 | 40/40 | 40/40 | — | — | 28.613 / 164.851 |
| esp32s3 | control-normal-v1 | 40/40 | 40/40 | — | — | 7.992 / 177.266 |
| esp32s3 | source-normal-v1 | 40/40 | 40/40 | — | — | 18.411 / 130.760 |
| esp32s3 | control-gtk-v1 | 300/300 | 20/20 | 120/120 | 119/120 | 30.378 / 173.616 |
| esp32s3 | source-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 26.512 / 145.865 |
| esp32s3 | source-restored-v1 | 40/40 | 40/40 | — | — | 15.040 / 82.466 |

A separate raw-pcap reader corroborates echo payload pairs, group sequences
and EAPOL counters. `eth10` captures both EAPOL directions; `br0` corroborates
station requests/replies but does not capture AP-originated G1. All capture
workers report zero drops, truncation and missing timestamps. Every completed
trial is retained, including packet gaps or incomplete rotations.

| Chip / GTK trial | Completed rotations / requested | Request counters absent at AP | Missing broadcast / multicast sequences | G1-to-G2 latency (ms, by counter) |
| --- | --- | --- | --- | --- |
| esp32c3 / control-gtk-v1 | 3/3 | `[]` | `[21]` / `[]` | `{'3': 33.923, '4': 63.798, '5': 77.584}` |
| esp32c3 / source-gtk-v1 | 3/3 | `[]` | `[]` / `[13]` | `{'3': 81.436, '4': 14.533, '5': 99.165}` |
| esp32s3 / control-gtk-v1 | 3/3 | `[]` | `[]` / `[13]` | `{'3': 106.147, '4': 42.762, '5': 43.64}` |
| esp32s3 / source-gtk-v1 | 3/3 | `[]` | `[]` / `[]` | `{'3': 19.784, '4': 18.41, '5': 28.325}` |

- `esp32c3/control-gtk-v1` misses broadcast sequence 21; present in `eth10`: `True`, `br0`: `True`. It occurs 161.623 ms after completed G2 counter 3; paired group capture separation is 0.11 ms.
- `esp32c3/source-gtk-v1` misses multicast sequence 13; present in `eth10`: `True`, `br0`: `True`. It occurs before the first completed group-key rotation; paired group capture separation is -0.122 ms.
- `esp32s3/control-gtk-v1` misses multicast sequence 13; present in `eth10`: `True`, `br0`: `True`. It occurs before the first completed group-key rotation; paired group capture separation is -0.08 ms.

## Cumulative timing observations

| Chip / GTK trial | PHY maximum (us) | Console maximum (us) | TX resume maximum (us) | RX age maximum (us) |
| --- | ---: | ---: | ---: | ---: |
| esp32c3 / control-gtk-v1 | 131 | 1830 | 1470 | 8539 |
| esp32c3 / source-gtk-v1 | 87 | 1889 | 1607 | 8537 |
| esp32s3 / control-gtk-v1 | 88 | 3747 | 1671 | 8394 |
| esp32s3 / source-gtk-v1 | 92 | 3942 | 1031 | 8471 |

These are cumulative maxima, not correlations to particular packets. The
capture review places group losses relative to key exchanges, but Ethernet
observations cannot locate a loss within the RF/device path or establish its
cause. Replacing tracking does not establish a packet-loss or timing fix.
The [earlier comparisons](PHY-ANALOG-VALIDATION.md) and their failures remain
part of the evidence.

## Restoration and remaining dependencies

Both boards were restored to ordinary source images and completed two further
connections each. Every flash checked explicit chip identity/security state;
S3 application images were signed and verified using the existing key. Only
the existing application slots were written. Owned router workers/files were
removed; monitor mode remains zero and persistent AP configuration is unchanged.
C3 finished disconnected; the final paired flasher holds S3 in ROM with the
ordinary source image retained.

Eight allocated vendor PHY members remain: TX gain, PLL, RX gain, register
programming, frequency control, initialization, TX calibration and RX
calibration. Vendor state and ROM dependencies remain. This milestone uses
one board per chip, one AP and short room-temperature trials. Other
temperatures, calibrated RF/power accuracy, sleep/coexistence and long-duration
reliability remain unvalidated.

All sixteen planned device trials and both restoration trials completed on their first recorded device attempt. Infrastructure and checker bring-up attempts are retained in the numeric report.
