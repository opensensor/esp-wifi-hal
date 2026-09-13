# Sensor lifecycle: C3/S3 comparison

This is the sensor milestone's historical comparison. The subsequent
[PBUS report](PHY-PBUS-VALIDATION.md) records the next source replacement and
its separate control/device trials.

The [sensor lifecycle implementation](PHY-SENSOR-LIFECYCLE.md) removes every
allocated input from `phy_tsens.o` in the tested C3 and S3 station images.
Implementation `2811a8e` extends the previous temperature milestone `915d3be`.
Both sides retain FoA `214311817b5234c1e9c911cd28a664cd392c366e` and the same
tracking cadence, logging profile and CPU frequency.

The control already uses the previous five source measurement helpers; it
retains the vendor lifecycle functions and table. Its lifetime probe was copied
from this implementation so both sides inspect the same state and callbacks.
The [numeric report](phy-sensor-lifecycle-validation.json) records the exact
image, map, source-file and private evidence hashes. Builds retain their actual
checkout revision plus compiled source hashes. Raw firmware, network identities,
captures and signing material remain private.

## Host and link checks

All 562,184 C3 and 569,768 S3 lifecycle instruction cases match production Rust
at optimization levels 0 and 2. The 22 focused oracle tests and 19 new allocation
tests pass with Python assertions enabled and disabled. The previous temperature,
HAL and dispatcher suites pass; ESP32/S2 `cargo check` compatibility checks pass.

| Ordinary station allocation, excluding mergeable strings | C3 control | C3 source | S3 control | S3 source |
| --- | ---: | ---: | ---: | ---: |
| `libphy.a` bytes | 35,173 | 34,893 | 32,913 | 32,575 |
| `phy_tsens.o` bytes | 280 | 0 | 342 | 0 |
| Allocated PHY members | 18 | 17 | 18 | 17 |

All new function/data aliases point to source objects; the source attribute
table matches the exact aligned 30-byte vendor table. Existing source printf,
wrapper, dispatcher and no-`libpp.a` gates still pass.

The net vendor reductions are 280 C3 bytes and 338 S3 bytes. S3's
`ram_set_chan_cal_interp` previously reused the `0x66666667` literal owned by
the removed sensor member. Its own four-byte literal must now remain, growing
that input from 104 to 108 bytes while its function body stays 104 bytes.
The GTK S3 links are eight bytes smaller on both sides, preserving the same
338-byte reduction. These numbers describe vendor input ownership, not total
firmware size savings.

The source `phy_xpd_tsens` implementation and all its loads are in IRAM, with
no flash calls or literals. Its original wrapper bytes remain inside the
shared `phy_api.o` IRAM input: 168 bytes on C3 and 105 on S3 for the whole
shared input, including unrelated routines. Source routing of that wrapper is
verified; elimination of those shared vendor bytes is not claimed.

## PHY lifetime and receive recovery

Each control/source lifetime image completed three cycles: initial enable,
nonempty calibration-output check, sensor/callback inspection, sole PHY guard
release, then wakeup. The initially empty calibration input reports the existing
`DataCheckFailed` status; the probe separately checks that full calibration
produced output. Later enables exercise the retained wakeup path.

All live inspections saw the sensor-off flag clear and the expected power bits:
C3 `0x400000`, S3 `0xc00000`. After each guard release, the software off flag
was one. The probe reads only software state after release because peripheral
clocks may be off. C3's installed power callback and S3's power-conversion and
sensor-code callbacks match their linked functions. Source shutdown addresses
match the replacement aliases.

All readings used DAC 15 and index 2. Recorded C3 temperatures were 35/33/33
for control and 30/28/28 for source; S3 was 31/30/30 and 32/32/31. These were
sequential runs without matched thermal conditions or an independent calibrated
thermometer. They do not establish absolute temperature accuracy. After wakeup,
C3 control/source each received two beacons; S3 received two/three.

Control and source RX probes passed pending-tail preservation, exhaustion and
recovery, OFDM transmission and the existing channel 1–11 scan on both chips.
This checks operation after lifecycle changes; it does not characterize RF
performance across channels or temperature ranges.

## WPA2 traffic

Ordinary station trials use two connections and 20 router-originated echoes
per connection, plus gateway echoes from the MCU. GTK trials run for 90 seconds
with three authenticated key requests ten seconds apart, 300 router echoes at
200 ms intervals, 20 gateway echoes and 120 broadcasts plus 120 multicasts.
Echo payloads are 512 bytes; group datagrams are 128 bytes at 500 ms intervals.

All ordinary control/source trials completed two connections with 40/40 router
and 40/40 gateway echoes. GTK results were:

| GTK trial | Router echoes | Gateway echoes | Broadcast | Multicast | Key exchange result |
| --- | ---: | ---: | ---: | ---: | --- |
| C3 control | 300/300 | 20/20 | 120/120 | 120/120 | Three exchanges |
| C3 source | 300/300 | 20/20 | 120/120 | 120/120 | Three exchanges |
| S3 control | 300/300 | 20/20 | 119/120 | 119/120 | Three exchanges |
| S3 source | 300/300 | 20/20 | 120/120 | 119/120 | Three exchanges; first acknowledgement retried |

Independent inspection of the AP interface and bridge captures corroborates
these counts. Captures are nonempty, their packet counts match the capture
statistics, and they report zero socket drops, truncation or missing timestamps.
Valid group packets arrive before, between and after new key installations.

S3 control missed broadcast sequence 42 and multicast sequence 103. Both are
present with valid payloads in both AP captures. The broadcast appeared about
656 ms after the second completed key reply, and the multicast about 21.159 s
after the third. S3 source missed multicast sequence 43, present at both AP
capture points about 1.173 s after its second completed key exchange. These
observations place gaps after completed handshakes, but do not identify the
cause within RF or receive processing.

S3 source also reported successfully transmitting G2 counter 3, which is absent
at both AP capture points. The AP repeated the same encrypted key material
1,000.158 ms later as G1 counter 4. The station correctly reported
`installed=false` and its counter-4 reply reached the AP. Subsequent requests
completed with counters 5 and 6. This is three new key installations and four
authenticated G1 deliveries. It reproduces the earlier recovered missing-G2
pattern; this milestone does not claim to fix it or establish a cause in the
sensor helpers.

| GTK router echo RTT | Control median / maximum | Source median / maximum |
| --- | ---: | ---: |
| C3 | 4.568 / 35.231 ms | 4.148 / 45.082 ms |
| S3 | 3.045 / 39.048 ms | 2.989 / 73.380 ms |

The samples include router scheduling and radio behavior. They do not establish
a latency improvement or resolve earlier long-tail timing observations.

After these trials, the ordinary source images without the rekey probe were
restored. Each restoration completed two connections and 40/40 echoes in both
directions. The numeric report records their image hashes and captures. C3
finished disconnected; S3 is held in ROM by the paired flasher, with its ordinary
source image in its application slot. Owned router workers were stopped and
the temporary tools removed; monitor mode remained zero.


## Limits and following work

The source implements the documented index domain, including an unrestricted
unused C3 initialization index. Other used indexes assert; the source does not
emulate unsupported raw indexes that wrap onto table data. Hardware exercised
the observed DAC/index setting, while the host oracle covers all five rows and
the selected argument boundaries.

C3 sensor-code acquisition and both chips' analog I2C and code-to-temperature
conversion remain ROM dependencies. The wider RF startup, register backup,
channel/PLL, calibration and power-tracking routines still require vendor code.
Removing one sensor member leaves 17 PHY members in these images.

Only the existing application slots were written, with chip/security checks
before each flash and S3 signatures verified using the existing local key.
Bootloaders, partitions, eFuses, keys and router configuration were unchanged.
The tests use one board per chip and one AP; intermittent packet losses and
latency tails from earlier milestones remain open unless separately resolved.
