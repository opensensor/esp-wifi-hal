# ESP32-C3 bring-up

OpenSensor integrates [okhsunrog's C3 port](https://github.com/esp32-open-mac/esp-wifi-hal/pull/22)
through commit `e65264ae992a02a4d776b33ad3e3784cf8f33260`, preserving its original
commits and authorship. That work supplied the C3 PAC, RX layout, TX power/control,
auto-ACK and TSF timer support. OpenSensor added SDK-checked HT20 short-GI encoding,
configured RX descriptor-address decoding, bounds checks and shared C3/S3 regression
coverage. This is an experimental port. Current C3 MAC initialization and eight
helpers are implemented in Rust; PHY code and ROM routines remain external.
See [Rust initialization results and unresolved failures](MAC-INIT.md). The
initial bring-up results below used vendor MAC initialization.

[PHY controls and slow-clock calibration](PHY-ROM.md) documents the next scoped
replacement, its instruction-trace checks, and short hardware validation.
Subsequent [network-stack fixes and device results](../network/PENDING-RESPONSES.md)
address first replies lost during ARP. The separate
[TX queue correction](../network/TX-QUEUE.md) covers completion ownership and
cancelled-buffer recovery; isolated gateway losses remain recorded.

## Hardware evidence, 2026-09-10

The board is an ESP32-C3 revision 0.4 with 4 MiB flash (the existing
Thingino provisioner target). The original flash was backed up before testing.
Only the factory application slot was written; bootloader and partition table
were retained. The provisioner application itself has not yet been ported to
this Rust driver. Tests used one WPA2 access point on channel 3.

- Stock ESP-IDF 5.4 baseline: three full init/scan/connect/DHCP/stop/deinit cycles,
  **60/60 gateway echo replies**, 512-byte payloads, advancing TSF.
- Rust `wifi_smoke`: eight received frames, including three OFDM; all ten RX
  descriptors held, returned in reverse order, and RX recovered; OFDM 6 Mbps
  transmission completed; MAC timer advanced.
- Rust FoA station: three WPA2/DHCP/reconnect cycles, **60/60 gateway echo replies**.
  The independently initiated host echo test received **58/60** (20, 19, 19).
  The first reply was missing in cycles 2 and 3, consistent with the separately
  reproduced smoltcp neighbor behavior documented in the S3 notes. This C3 run
  alone does not establish the cause of each lost packet.

The stock test fully stops and deinitializes Wi-Fi each cycle; the Rust station
example reconnects its existing initialized driver. Those are different lifecycle
tests. These short checks do not establish sustained reliability. HT rate sweeps,
C3 TSF/TBTT interrupt timing, power saving, coexistence, AP mode and the provisioner
application workload remain unvalidated. No C3 hardware security settings changed.

Machine-readable image hashes and source hashes are in [validation.json](validation.json).
Raw station logs, binaries and the provisioner backup are private because they may
contain network configuration.

## Build and repeat

Select exactly one chip feature. The workspace pins the credited C3 Wi-Fi PAC
mapping in OpenSensor's `research/esp32c3-wifi-0.32` branch at
`9be190016260ef195c97f7aa5aa7c576a1646890`; downstream application manifests need
the same crates.io patch. The driver uses PAC 0.32.3, while esp-hal 1.1.2 uses
PAC 0.33.0 internally; both versions are present in this tested build.

With the installed `esp` Rust toolchain and its environment loaded:

```sh
sh docs/esp32s3/tests/run-rust-tests.sh
cd examples
ESP_LOG=info cargo +esp build --locked --release \
  --target riscv32imc-unknown-none-elf --features esp32c3 --bin wifi_smoke

# Set SSID and PASSWORD privately in the build environment first.
ESP_LOG=info cargo +esp build --locked --release \
  --target riscv32imc-unknown-none-elf --features esp32c3,foa-smoke --bin sta_smoke
```

The examples' Cargo configuration builds core/alloc for the selected target.
The tested compiler is esp Rust 1.97.0.0. Station credentials are compiled into
the image; do not upload it. Generate an ESP32-C3 app image with `espflash save-image`
and use the board's actual partition layout when flashing. This board's factory
slot begins at `0x10000` and has size `0x100000`; that is board-specific.

## Register corrections

In the matching C3 ESP-IDF SDK, `mac_tx_set_htsig` uses high byte `0x07` for
long GI and `0x87` for short GI on the nonaggregated HT20 path. Short GI is bit 31,
not bit 7. The shared encoding tests retain other PLCP fields and distinguish
hardware rate codes 16–23 from 24–31.

`mac_rxbuf_init` programs descriptor high-address register `0x60033c64`.
`hal_mac_rx_get_last_dscr` combines its upper bits with LAST at `0x60033090`;
`wDev_AppendRxBlocks` checks NEXT at `0x6003308c` for zero. C3 now decodes the
low 20-bit offset with the configured high bits and treats zero as an empty
hardware queue. Both chip configurations exercise the actual DMA list tests.
