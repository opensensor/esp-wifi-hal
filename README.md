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
channel tuning, power tracking and internal PHY ROM dependencies remain external;
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
station results. RF initialization and calibration are still vendor code.

The [source PHY dispatcher](docs/network/PHY-DISPATCHER.md) replaces the
C3/S3 RAM dispatch body while retaining its analog helpers and callback table.
Its original-instruction comparisons, target checks and device report include
the observed S3 RX-probe failure and intermittent host echo loss.

The next [temperature-sensor milestone](docs/network/PHY-TEMPERATURE.md)
records the current tested images' remaining PHY allocations and the C3/S3
read/calibration boundaries to reconstruct. Temperature sensing remains vendor
code; the document defines the required source, linker and device comparisons.

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
