# Temperature replacement: C3/S3 device comparison

The [five Rust temperature helpers](PHY-TEMPERATURE-IMPLEMENTATION.md) passed
the original-instruction comparisons, full-image link checks, PHY lifetime,
RX recovery and WPA2 traffic tests on one C3 and one S3. Both source station
images completed three GTK rotations with 300/300 router echoes, 20/20 gateway
echoes and 120/120 each for broadcast and multicast in the first comparison.
One C3 GTK acknowledgement needed a retry. A repeat with the identical C3
image completed all three exchanges without that retry, but missed one
broadcast. Both C3 observations and an S3 vendor broadcast gap remain open.

Implementation commit `6515f87` follows baseline `c8ae4dd`. Both sides retain
FoA `214311817b5234c1e9c911cd28a664cd392c366e`, including the previous M4 retry
and GTK fixes. The [machine-readable report](phy-temperature-validation.json)
records image/map hashes, compiled source hashes, callback addresses, allocation
checks, packet counts and private evidence hashes. Images and captures remain
private. Builds made before the implementation commit retain their actual
checkout revision and source-file hashes rather than claiming a clean checkout.

## Original instructions and linked ownership

Production Rust matches 366,074 C3 and 366,099 S3 original-instruction cases
at optimization levels 0 and 2. The 19 oracle tests and 19 allocation tests also
pass with Python assertions disabled. Each source test suite checks all expected
returns and ordered events, plus invalid table indexes; the existing HAL and
dispatcher suites pass. ESP32 and S2 `cargo check` compatibility checks pass.

The full station audits require all five original text/literal inputs absent
and all original aliases pointing at allocated source functions. They also
retain the previous source printf/wrapper/dispatcher gates, required vendor
helpers, state, the aligned 30-byte attribute table and no allocated `libpp.a`.
Disassembly verifies C3's same-object `get_temp_init` call and both callback
installers. The lifetime probe additionally checks those installed pointers
against the linked function addresses on the boards.

| Ordinary station image: non-string allocation | C3 vendor | C3 source | S3 vendor | S3 source |
| --- | ---: | ---: | ---: | ---: |
| `libphy.a` bytes | 35,471 | 35,173 | 33,160 | 32,913 |
| `phy_tsens.o` bytes | 578 | 280 | 589 | 342 |
| PHY members | 18 | 18 | 18 | 18 |

The net vendor reduction is 298 bytes on C3 and 247 on S3. Function body sums
alone would miss literal/relaxation changes. The GTK S3 images have 8 fewer
PHY bytes on each side because they are different links; their reduction is
also 247 bytes. This is vendor input removal, not a whole-firmware size saving.
The remaining sensor initialization, power, conversion and RF dependencies
are described in the implementation document.

## Calibration, wakeup and RX

For each chip, vendor and final source lifetime images each completed three
cycles with the sole PHY guard: enable, nonempty calibration-output check,
temperature/callback inspection, release, then enable again. The retained
`DataCheckFailed` status describes the initially empty calibration input, as
established in [the earlier lifetime work](PHY-SOURCE-VALIDATION.md); it does
not mean the full-calibration output was empty or wakeup failed.

Every recorded sensor check observed DAC 15 and index 2. Final C3 temperatures
were 39/38/37 for vendor and 40/38/38 for source; S3 was 34/34/34 versus
35/34/34. These are successive room-temperature trials, not simultaneous
measurements or an independent thermometer comparison. Code-to-temperature
conversion remains a vendor callback.

C3 used the inspected ROM read/code/convert/write entries. S3 used its ROM
I2C/conversion entries and the retained `ram_tsens_code_read` body. Source
outer callback pointers matched the replacement functions on all three cycles;
C3's separate forwarding slot was checked too. Both implementations received
beacons after wakeup.

Vendor and source RX probes on each chip passed the pending-tail preservation,
buffer exhaustion, recovery and OFDM transmit checks. Those probes also exercise
channel selection across the existing 1–11 scan. They do not characterize RF
performance across all channels and conditions.

## WPA2 traffic and retained discrepancies

The router generated 512-byte echoes every 200 ms, avoiding the host's separate
Wi-Fi hop. Ordinary images each completed two WPA2/DHCP connections and 40/40
echoes in each direction. GTK images ran one 90-second connected window with
three authenticated key requests ten seconds apart. The router also sent 120
128-byte broadcasts and 120 multicasts, one of each every 500 ms.

| GTK trial | Router echoes | Gateway echoes | Broadcast | Multicast | AP-confirmed result |
| --- | ---: | ---: | ---: | ---: | --- |
| C3 vendor | 300/300 | 20/20 | 120/120 | 120/120 | Three exchanges |
| C3 source | 300/300 | 20/20 | 120/120 | 120/120 | Three exchanges; first acknowledgement retried |
| C3 source, identical-image repeat | 300/300 | 20/20 | 119/120 | 120/120 | Three exchanges without retry |
| S3 vendor | 300/300 | 20/20 | 119/120 | 120/120 | Three exchanges |
| S3 source | 300/300 | 20/20 | 120/120 | 120/120 | Three exchanges |

AP captures corroborate the requests and G1/G2 counters for the selected
station. All capture files are nonempty with zero reported socket drops,
truncation or missing kernel timestamps. Valid group payloads arrive before,
between and after new key installations, using both rotating key IDs.

In the C3 source trial, the MCU reported sending G2 for counter 3, but neither
the AP interface nor bridge capture contains it. The AP sent G1 counter 4
1,000.18 ms later with the same encrypted key data, nonce, IV and RSC. The
station reported `installed=false` for this repeated key and its counter-4
reply appears in both captures. Subsequent requests completed with counters
5 and 6. The report retains four authenticated G1 deliveries and three new
installations; it does not mistake every delivery for a new key. The precise
cause of the first missing G2 is unresolved.

The S3 vendor trial and the C3 identical-image repeat each missed broadcast
sequence 41 at the MCU. Both AP interface and bridge captures contain the
missing packet and all 120 broadcast and multicast datagrams. The missing
broadcast follows the second AP-observed G2 by about 187 ms on S3 vendor and
207 ms on C3 source; the adjacent multicast arrives at the MCU in both trials.
No echo or group-datagram gap occurred in the S3 source trial. These observations
do not locate the loss within RF or receive processing, or establish a cause
in the temperature helpers. The earlier intermittent losses remain unresolved.

| GTK router echo RTT | Vendor median / maximum | Source median / maximum |
| --- | ---: | ---: |
| C3 | 4.158 / 37.763 ms | 4.002 / 143.878 ms |
| S3 | 3.043 / 230.482 ms | 3.092 / 58.129 ms |

The identical-image C3 repeat had a 3.920 ms median and 24.823 ms maximum.
These include router scheduling and radio behavior. Latency tails remain; the
mixed direction of the maxima is not evidence of an improvement or regression
caused by these five functions.

## Scope

Only application slots were flashed, with chip type/security state checked
before each write and the existing S3 signing key used locally. Bootloaders,
partitions, eFuses and router configuration were unchanged. Tests run one board
at a time, with the other held in ROM. Host-generated case files and captured
frames are not replacements for environmental RF testing.

After the GTK trials, both boards were restored to their ordinary source
station images without the rekey probe. Each restoration completed two
connections with 40/40 router and 40/40 gateway echoes. These restored image
hashes and captures are included in the machine-readable report. The final C3
trial completed and disconnected; S3 is held in ROM by the paired flasher,
with its ordinary image in the application slot.

The five-row source guard deliberately asserts on an unsupported index at a
row access, where the original routine would read beyond the table. All five
rows and selector boundaries are covered by the host oracle; hardware testing
observed only the supported room-temperature setting above. Temperature-chamber
coverage and replacement of the remaining sensor/analog dependencies are future
milestones.
