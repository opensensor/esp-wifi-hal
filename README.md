# OpenSensor esp-wifi-hal

[![Host regressions](https://github.com/opensensor/esp-wifi-hal/actions/workflows/host-regressions.yml/badge.svg)](https://github.com/opensensor/esp-wifi-hal/actions/workflows/host-regressions.yml)

An experimental asynchronous Rust Wi-Fi driver for ESP32-series chips, using
Embassy. This is the OpenSensor Engineering fork of
[esp32-open-mac/esp-wifi-hal](https://github.com/esp32-open-mac/esp-wifi-hal),
maintained independently in the [OpenSensor organization](https://github.com/opensensor).
This repository is the canonical home for our development, issues and pull requests.
The [OpenSensor ESP repository index](FORKS.md) links the companion stack,
register definitions, C driver and reverse-engineering tools.

**AI-assisted and AI-generated contributions are welcome.** We review changes
for correctness, clarity, reproducible evidence and licensing. Contributors own
their submissions and the work needed to address review feedback. See
[Contributing](CONTRIBUTING.md#ai-assisted-contributions) for the policy.

## Current scope

The driver crate is in `esp-wifi-hal/`, PHY rate types are in `esp-wifi-rates/`,
and applications are in `examples/`. Select exactly one chip feature:
`esp32`, `esp32s2`, `esp32s3` or `esp32c3`. The `critical_section` feature allows using the
driver across cores; without it, the driver does not use critical sections.

The S3 port adds Rust MAC initialization, RX/TX handling and hardware crypto
integration. [S3 MAC helper initialization](docs/esp32s3/MAC-HELPERS.md) now runs
in Rust with no `libpp.a` code/data in the tested images. PHY and ROM code remain, so this is
a partial Wi-Fi deblob. The S3 feature requires the PAC patch pinned in the
manifests; application workspaces also need that patch.

Extended tests have seen an intermittent DHCP timeout, although a repeat of the
same image completed ten cycles; see the [validation limits](docs/esp32s3/MAC-HELPERS.md#device-validation).

The C3 port integrates okhsunrog's existing work, with additional RX address and
HT20 corrections. On the provisioner board, Rust WPA2/DHCP testing passed three
cycles with 60/60 gateway replies; RX buffer recovery and OFDM TX also passed.
C3 now also has Rust MAC initialization, with no allocated `libpp.a` sections
in the tested station image. Its final ten-cycle repeat passed 200/200 gateway
echoes and 185/200 host echoes, following an initial connection timeout. Those
are pre-network-fix results; the reports retain the failures. See the
[C3 build and attribution notes](docs/esp32c3/README.md) and
[initialization evidence](docs/esp32c3/MAC-INIT.md).

Further work replaces direct AGC and low-rate PHY helpers in Rust on both chips
and uses measured C3 slow-clock calibration. RF initialization/calibration,
channel tuning and internal PHY ROM dependencies remain partly external;
see the [C3](docs/esp32c3/PHY-ROM.md) and [S3](docs/esp32s3/PHY-ROM.md) inventories.
The [original dependency audit](docs/network/PHY-DEPENDENCIES.md) records exact
allocated archive sizes and distinguishes direct ROM calls from installed RAM
callbacks.

The C3/S3 source milestone also replaces two small
[PHY wrappers](docs/network/PHY-WRAPPERS.md) and builds the MIT-licensed
printf support library from C source. Both the driver and its vendored
`esp-phy` adapter pin the same reviewed OpenSensor sys revision; other radio
archives retain the published 0.2.0 baseline. See the
[combined source and device validation](docs/network/PHY-SOURCE-VALIDATION.md)
for the remaining allocations, formatter ABI, RX recovery, PHY lifetime and
station results. Wider RF initialization and calibration still depend on vendor code.

The [source PHY dispatcher](docs/network/PHY-DISPATCHER.md) replaces the
C3/S3 RAM dispatch body while retaining its analog helpers and callback table.
Its original-instruction comparisons, target checks and device report include
the observed S3 RX-probe failure and intermittent host echo loss.

Five C3/S3 [temperature measurement and DAC-range helpers](docs/network/PHY-TEMPERATURE-IMPLEMENTATION.md)
now use Rust, with original-instruction tests and linker checks for all callers.
The [device comparison](docs/network/PHY-TEMPERATURE-VALIDATION.md) records
initialization, wakeup, RX recovery and WPA2 traffic. The subsequent
[sensor lifecycle replacement](docs/network/PHY-SENSOR-LIFECYCLE.md) adds power,
initialization, tracking-state helpers and the attribute table, eliminating
allocated `phy_tsens.o` inputs on C3 and S3. C3's ROM sensor-code callback,
analog conversion and the wider RF initialization/calibration remain vendor
dependencies. Its [device report](docs/network/PHY-SENSOR-LIFECYCLE-VALIDATION.md)
keeps observed packet losses and remaining dependencies explicit.

The subsequent [PBUS replacement](docs/network/PHY-PBUS.md) removes all allocated
`phy_pbus.o` code and data on C3/S3, leaving 16 PHY archive members in the tested
station images. Rust programs the chip-specific bus tables, saves the range
registers and preserves calibration-mode transitions through the retained ROM
callbacks. The [PBUS comparison](docs/network/PHY-PBUS-VALIDATION.md) covers
original-instruction tests, live range checks, wakeup, traffic and GTK rotation.
The broader RF/ROM dependencies and intermittent packet losses remain open.

The [complete analog I2C replacement](docs/network/PHY-I2C.md) removes
`phy_i2c.o`, and the [PHY API replacement](docs/network/PHY-API.md) removes
`phy_api.o`, leaving **14 vendor PHY members** in the tested C3/S3 images.
The [API device comparison](docs/network/PHY-API-VALIDATION.md) records
instruction-oracle checks, three-cycle wakeup/shutdown probes, RX recovery
and WPA2 group-key rotation. RF calibration, channel/frequency helpers,
vendor state and ROM callbacks remain dependencies; packet losses remain
tracked with their original evidence.

The [basic PHY replacement](docs/network/PHY-BASIC.md) subsequently removes
`phy_basic.o`, leaving **13 vendor PHY members** in the tested C3/S3 images.
Rust supplies I2C master reset, channel-14 configuration and S3 calibration
interpolation while preserving the existing ROM channel binding. Its
[device comparison](docs/network/PHY-BASIC-VALIDATION.md) records 841,856
instruction-oracle cases, native placement checks, lifecycle/RX probes and
traffic results, including broadcast gaps and an incomplete requested rekey.

The [PHY feature replacement](docs/network/PHY-FEATURE.md) then removes
`phy_feature.o`, leaving **12 vendor PHY members** in the tested C3/S3 images.
It supplies the ROM backup adapters, power adjustment and channel-mode helper
with 414,480 original-instruction cases at two optimization levels. The
[device comparison](docs/network/PHY-FEATURE-VALIDATION.md) records lifecycle,
RX, ordinary traffic and group-key rotation results, preserving observed
packet gaps and remaining RF/ROM dependencies.

The [PHY debug replacement](docs/network/PHY-DEBUG.md) removes `phy_debug.o`,
leaving **11 vendor PHY members** in the tested C3/S3 images. It supplies IQ
conversion, bias reference and voltage calculation with 748,260 instruction
cases at two optimization levels. Its
[device comparison](docs/network/PHY-DEBUG-VALIDATION.md) includes guarded IQ
vectors, callback observations and actual traffic results, including losses.

The [power-detector replacement](docs/network/PHY-PWDET.md) removes
`phy_pwdet.o`, leaving **10 vendor PHY members** in the tested C3/S3 images.
Rust supplies tone/sample sequencing, reference arithmetic and power
calculation, checked against 913,536 instruction cases at O0 and O2. Its
[device comparison](docs/network/PHY-PWDET-VALIDATION.md) records guarded
reference vectors, the sixteen-byte ROM sample-buffer contract, RX recovery,
ordinary traffic and group-key rotation. ROM ADC/conversion callbacks and
wider RF calibration remain dependencies; historical packet gaps remain open.

The [RC measurement/calibration replacement](docs/network/PHY-ANALOG.md)
removes `phy_analog_cal.o`, leaving nine vendor PHY members at that milestone. It supplies ordered masked analog operations, calibration
arithmetic and C3's writable divisor globals, with 541,656 original-instruction
cases at O0 and O2. The [device comparison](docs/network/PHY-ANALOG-VALIDATION.md)
records normal calibration, unchanged calibrated early returns, native ABI
checks, RX recovery and paired WPA2/GTK traffic. ROM analog access and
soft-double arithmetic remain dependencies; packet-loss investigations remain
open.

The [PHY tracking replacement](docs/network/PHY-TRACK.md) removes all allocated
`phy_track.o` inputs, leaving **eight vendor PHY members** on C3/S3. Rust
preserves busy polling, ULP/PLL/power tracking, voltage offset and chip-specific
wrappers. Production passes 483,238 original-instruction cases at O0 and O2;
native checks cover 60 emitted bodies across eight source profiles. The
[paired device report](docs/network/PHY-TRACK-VALIDATION.md) records lifetime,
RX, reconnects, GTK rotation and observed packet gaps. RF calibration/gain
internals and ROM callbacks remain dependencies; packet-loss work remains open.

The [RF PLL replacement](docs/network/PHY-RFPLL.md) removes every allocated
`phy_rfpll.o` input through 16 C3 / 18 S3 Rust entries, leaving seven allocated
vendor PHY members. It preserves chip-specific frequency arithmetic, bounded
capacitor calibration, MMIO offset updates and channel helpers. The original
instructions match 289,110 host cases at O0/O2; compiled firmware adds 6,456
native case executions. The [paired report](docs/network/PHY-RFPLL-VALIDATION.md)
records board trials and remaining limits.

The [hardware-frequency replacement](docs/network/PHY-HW-FREQ.md) supplies all
11 `phy_hw_freq.o` functions per chip in Rust. It preserves IRAM helpers,
nine-argument I2C transport, frequency-memory packing and channel sequencing.
The 2,860 host cases at O0/O2 reach every recorded instruction and branch edge;
ownership checks also enforce the IRAM placement of the three small helpers.

The examples now pin OpenSensor stack corrections for
[replies lost during neighbor discovery](docs/network/PENDING-RESPONSES.md) and
[TX queue completion ownership/buffer recovery](docs/network/TX-QUEUE.md).
MAC completion tracing also exposed [constant-zero station sequences](docs/network/STA-SEQUENCES.md);
generated data, EAPOL and authentication/association frames now request driver
sequence assignment.
The driver also restores [Retry after MAC failures](docs/network/MAC-RETRIES.md),
and FoA rejects [equal received CCMP packet numbers](docs/network/STA-REPLAY.md).
Both corrections have production-code host regressions and dedicated C3/S3
traffic reports. The [reviewed C comparison](docs/esp32s3/C-RUST-CONTROL.md)
passed 200/200 pings in both directions; Rust still has documented intermittent
losses, including explicit CTS timeouts and losses after successful completions.
The smoltcp correction passed ten cycles on each chip with 200/200 host and
200/200 gateway replies; a C3 stress run received all 1,000 unique replies plus
six duplicates. Later combined tests still observed isolated gateway loss.
Connection timeouts, duplicate reception and sustained radio reliability remain
under investigation; the linked evidence records each image and failed run.

FoA now handles [WPA2 group-key rotation](docs/network/GTK-REKEY.md) without
reinstalling keys on retries. Final S3/C3 trials completed three GTK exchanges
per board with all 600 router-originated echoes and 240 multicast datagrams;
one C3 broadcast was missing. The report includes the M4-retry correction,
capture-harness failures and the remaining limits of these short trials.
The subsequent [EAPOL completion fix](docs/network/EAPOL-TX-COMPLETION.md)
returns an explicit error when the queue loses a completion, instead of
reporting success. Its C3/S3 comparison keeps the PHY implementation fixed.

The recorded S3 hardware validation includes:

- Three WPA2/FoA reconnect cycles with **60/60 device-to-gateway ping replies**.
- RX buffer exhaustion/recovery, OFDM TX completion and MAC timer checks.
- A separate host echo-responder result of 58/60; the first-ping losses were
  reproduced in smoltcp's ARP/neighbor handling without ESP hardware.
- An extended run with seven completed cycles and 140/140 gateway replies,
  followed by an unresolved connection timeout on cycle eight.

ESP32 and S2 compile checks also passed; this S3 work did not hardware-test
those chips. AP mode, multiple VIFs, HT rate sweeps, power saving, Bluetooth
coexistence and long-duration reliability remain unvalidated.

See [S3 build and validation notes](docs/esp32s3/RUST.md), the
[machine-readable results](docs/esp32s3/rust-validation-summary.json), and the
[reviewed C reference](docs/esp32s3/README.md) for evidence and reproduction.

## Build and test

Install the esp Xtensa Rust toolchain using the
[esp-rs installation guide](https://docs.esp-rs.org/book/installation/index.html)
and source its export script.

C3/S3 also require the Espressif target C compiler and archiver to build printf:
`riscv32-esp-elf-gcc` / `riscv32-esp-elf-ar`, or
`xtensa-esp32s3-elf-gcc` / `xtensa-esp32s3-elf-ar`. Put them on PATH or set the
target-specific `CC_*` and `AR_*` overrides described in the
[source-build notes](docs/network/PHY-SOURCE-VALIDATION.md#reproduce-the-probes).
Then:

```sh
git clone https://github.com/opensensor/esp-wifi-hal.git
cd esp-wifi-hal
sh docs/esp32s3/tests/run-rust-tests.sh

cd examples
ESP_LOG=info cargo +esp build --locked --release \
  --target xtensa-esp32s3-none-elf --features esp32s3 --bin wifi_smoke
```

For the WPA2 station example, set `SSID` and `PASSWORD` in the build environment
and follow the [station test instructions](docs/esp32s3/RUST.md#hardware-tests).
Those values are embedded in the resulting binary; keep that artifact private.
Use the documented application-only signing/flashing flow for a secured board.

Use this Git checkout to get the fork's changes. Existing crates.io releases
under the same crate names do not automatically include this fork's work.
No separate OpenSensor crate release has been published.

## Contribute

Send [issues](https://github.com/opensensor/esp-wifi-hal/issues) and
[pull requests](https://github.com/opensensor/esp-wifi-hal/pulls) here, targeting
`main`. [Contributing](CONTRIBUTING.md) describes review expectations and the
host checks that run in CI. Hardware logs should identify the source revision,
board and toolchain, including failures and untested paths.

The initial S3 reconstruction used a local **qwen3.8-flash-next** model and
matteius's closed-source **re-framework**, followed by manual review, corrections,
Rust implementation and device testing. The contribution and its reproduction
tests do not require that private harness.

For similar reverse engineering, embedded Rust or firmware work, matteius is
seeking additional contract hours through **OpenSensor Engineering**.

## Origins and license

This fork builds on the original esp32-open-mac project, Frostie314159's Rust
driver, and contributions from its community. The S3 port also credits
okhsunrog's C3 register and driver work in its validation notes. Git history,
copyright notices and original author attribution are preserved.

The crates retain their **MIT OR Apache-2.0** licensing; see their license files.
This remains experimental software, with the warranty disclaimers in those
licenses.

## Technical Notes
The ESP32 WiFi peripheral has five TX slots, which we number 0-4. The MMIO addresses, where these are configured are in reverse order. This means, that slot zero starts at the HIGHEST address and slot four at the lowest. This numbering is also suggested by the TX status registers. We could in theory reverse this ordering to ascending addresses, this would however cause headaches with TX slot status handling, so we chose to stick with descending addresses. This is also the way the proprietary stack handles this.

Each TX slot is a hardware transmit queue, four of which directly map to IEEE 802.11 access categories (ACs). The exact mapping is provided in the following table.

Slot | Queue | AC index
-- | -- | --
0 | Beacon | N/A 
1 | Background | 1
2 | Best Effort | 0
3 | Video | 2 
4 | Voice | 3

We have no idea, why they didn't just stick with the AC index order for the slots...
