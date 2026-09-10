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
`esp32`, `esp32s2` or `esp32s3`. The `critical_section` feature allows using the
driver across cores; without it, the driver does not use critical sections.

The S3 port adds Rust MAC initialization, RX/TX handling and hardware crypto
integration. [S3 MAC helper initialization](docs/esp32s3/MAC-HELPERS.md) now runs
in Rust with no `libpp.a` code/data in the tested images. PHY and ROM code remain, so this is
a partial Wi-Fi deblob. The S3 feature requires the PAC patch pinned in the
manifests; application workspaces also need that patch.

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
and source its export script. Then:

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
