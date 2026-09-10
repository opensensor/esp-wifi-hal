# OpenSensor ESP repositories

These repositories form OpenSensor Engineering's independently maintained ESP
Wi-Fi development and reverse-engineering workspace. Contributions go to the
OpenSensor repositories. AI-assisted and AI-generated contributions are welcome
under the [contribution policy](CONTRIBUTING.md#ai-assisted-contributions).
Each fork preserves its source history, author credits and existing licenses.

| Repository | Purpose | Source |
| --- | --- | --- |
| [esp-wifi-hal](https://github.com/opensensor/esp-wifi-hal) | Rust MAC driver; includes our experimental S3 port and validation | [esp32-open-mac/esp-wifi-hal](https://github.com/esp32-open-mac/esp-wifi-hal) |
| [esp32-open-mac](https://github.com/opensensor/esp32-open-mac) | C Wi-Fi driver and ESP32 reverse-engineering work | [esp32-open-mac/esp32-open-mac](https://github.com/esp32-open-mac/esp32-open-mac) |
| [FoA](https://github.com/opensensor/FoA) | Rust IEEE 802.11 stack | [esp32-open-mac/FoA](https://github.com/esp32-open-mac/FoA) |
| [foa-example-project](https://github.com/opensensor/foa-example-project) | Starter application for FoA | [esp32-open-mac/foa-example-project](https://github.com/esp32-open-mac/foa-example-project) |
| [esp32-open-mac-docs](https://github.com/opensensor/esp32-open-mac-docs) | Register and reverse-engineering documentation | [esp32-open-mac/esp32-open-mac-docs](https://github.com/esp32-open-mac/esp32-open-mac-docs) |
| [qemu-esp32](https://github.com/opensensor/qemu-esp32) | ESP32 Wi-Fi reverse-engineering emulator, on `esp-develop` | [esp32-open-mac/qemu](https://github.com/esp32-open-mac/qemu) |
| [esp-pacs](https://github.com/opensensor/esp-pacs) | Register definitions; includes our S3 Wi-Fi mapping | [esp-rs/esp-pacs](https://github.com/esp-rs/esp-pacs) |
| [esp-hal](https://github.com/opensensor/esp-hal) | Rust HAL and PHY integration | [esp-rs/esp-hal](https://github.com/esp-rs/esp-hal) |
| [esp-wifi-sys](https://github.com/opensensor/esp-wifi-sys) | Wi-Fi bindings and binary integration | [esp-rs/esp-wifi-sys](https://github.com/esp-rs/esp-wifi-sys) |

## Integration status

`esp-wifi-hal` has the tested S3 work on `main`. Its PAC dependency is pinned to
the OpenSensor `esp-pacs` commit
`37b54bd9ad62de17b17a8d7984a2ace5e73d63dd` on `research/esp32s3-wifi-0.35`.
This is the same PAC source tested earlier, now available from the organization.
The current-PAC version of that mapping is on `esp-pacs/main` and
`research/esp32s3-wifi`.

The other companion forks begin with their upstream code and our fork policy.
The station test still uses the locked published FoA and esp-hal dependencies;
their OpenSensor default branches have not been substituted or hardware-tested
as a new combination. The bindings repository still integrates vendor binaries;
forking it does not remove those dependencies.

The S3 test results and remaining connection timeout are documented in
[the validation guide](docs/esp32s3/RUST.md). Those results apply to its recorded
source and dependency revisions, rather than every companion repository's head.
