# S3 MAC helper replacement

The S3 Rust MAC initialization now implements the eight remaining helper
functions that the tested FoA station application previously retained from
`libpp.a`. Their implementation is in
[`s3_mac_helpers.rs`](../../esp-wifi-hal/src/s3_mac_helpers.rs).
The station and low-level smoke builds allocate no code or data from `libpp.a`.
This is an application-specific linkage result: PHY initialization, calibration,
channel control, power tracking and ROM routines still remain external. It does
not make the complete ESP32-S3 radio firmware open source, replace every function
in the archive, or remove the dependency on `esp-wifi-sys-esp32s3`.

## Reviewed input and behavior

This increment was reviewed directly from Xtensa disassembly of the previous
tested station ELF, with literal values resolved from that same linked image.
The archive is `esp-wifi-sys-esp32s3` 0.2.0's `libpp.a`, SHA-256
`0af323b9be8eeee7b40c43460535614cf7a9ef6be99600c4318523bf342fd8b4`.
The baseline ELF SHA-256 is
`80ffc2f17fc7af293150fe0475de51975c3b3d55acfb32701f1a29a4ec4c9e01`.
The linked addresses below identify this exact baseline, not fixed ROM entry
points. The [machine-readable evidence](mac-helper-validation.json) also records
archive-member hashes, tested images and source hashes.

| Original helper | Member | Baseline address | Preserved behavior |
| --- | --- | --- | --- |
| `hal_crypto_init` | `hal_crypto.o` | `0x4203c51c` | Five ordered defaults at `0x60033800..0x60033810`, then set `0x19` at `0x60033840` while preserving other bits. |
| `hal_attenna_init` | `hal_mac_tx.o` | `0x4203c568` | Two passes over eight descending slots at stride `0x4c`, starting at `0x60034314`; then two shared antenna-register updates. Vendor spelling retained. |
| `hal_mac_rate_autoack_init` | `hal_mac_tx.o` | `0x4203c5f0` | Write zero to `0x60033418`, then `0x19191919` to `0x6003340c`. |
| `hal_coex_pti_init` | `hal_coex.o` | `0x4203c480` | Set bit 1 at `0x60035084`. |
| `hal_set_rx_active_pti` | `hal_coex.o` | `0x4203c49c` | Update only bits 0..3 at `0x600332ac`, masking the input to four bits. |
| `hal_set_rx_ack_pti` | `hal_coex.o` | `0x4203c4bc` | Update only bits 4..7 at `0x600332ac`. |
| `hal_set_wifi_default_pti` | `hal_coex.o` | `0x4203c4e4` | Update only bits 8..11 at `0x60035094`. |
| `hal_timer_update_by_rtc` | `hal_tsf.o` | `0x4203c61c` | Enable bit 25 at `0x60035024`, then replace the low 18 calibration bits at `0x60035058`. Disable only clears the enable bit. |

Every access remains a volatile 32-bit transaction. In particular, antenna
initialization retains all 68 reads/writes in the original order: the first pass
clears slot selection, then the second pass clears bit 3, sets bit 5 and clears
bit 4 through three separate read/modify/write operations per slot. Combining
these updates into one write would not preserve the observed transaction
sequence. RTC enable follows the original low-byte argument semantics, and
calibration values are masked to 18 bits. The disabled branch was separately
disassembled at its branch target to avoid decoding the preceding alignment
padding as an instruction.

The coexistence helpers only establish register defaults. They do not implement
Bluetooth coexistence scheduling. Crypto initialization does not replace PHY
calibration or the Rust driver's existing key-slot programming.

## Regression checks

Run the existing host suite from the repository root:

```sh
sh docs/esp32s3/tests/run-rust-tests.sh
```

Six new test groups check instruction-derived MMIO traces for all eight helpers.
They exercise four initial register patterns, all 256 byte priorities plus
larger values, reserved-bit preservation, every antenna slot and both RTC
branches including nonzero high bytes with a zero low byte. The existing
`hal_mac.o` C/Rust differential still mocks its helper-call boundary; the new
trace tests independently exercise the actual helper implementations. These
checks cover register behavior, not a proof of RF equivalence.

To audit an application's actual archive contribution, produce a GNU linker map:

```sh
cd examples
# SSID and PASSWORD must already be present in the build environment.
ESP_LOG=info cargo +esp rustc --locked --release \
  --target xtensa-esp32s3-none-elf --features esp32s3,foa-smoke \
  --bin sta_smoke -- -C link-arg=-Wl,-Map=sta.map
```

Inspect allocated input sections after `Linker script and memory map`, not the
archive extraction list or discarded sections. The tested images have no
allocated `libpp.a(...)` sections and no original C symbols for these eight
helpers. Their remaining vendor archive contributions are `libphy.a` and
`libprintf.a`; ROM code remains in use as well. Seeing `LOAD .../libpp.a` only
means the linker was given the archive, not that its code reached the image.

## Device validation

The secured S3 was tested using its existing signing key and app partition only.
The bootloader, partition table and eFuses were not changed. See
[the Rust port's deployment notes](RUST.md#hardware-tests).

- The station test completed three WPA2/DHCP/disconnect cycles and all **60/60
  device-to-gateway pings** with 512-byte payloads.
- Host-to-device automatic ICMP replies remained **58/60**: the first echo after
  reconnect was missing in cycles 2 and 3. This matches the separately reproduced
  [smoltcp neighbor-cache behavior](RUST.md#ping-loss-and-rx-queue-diagnosis).
- The low-level smoke test received six frames, including three OFDM frames,
  loaned out all ten RX buffers, returned them in reverse order and observed RX
  recovery. OFDM 6 Mbps TX completion and an advancing MAC timer also passed.

These checks do not test AP mode, Bluetooth coexistence, all PHY rates, full
PHY/MAC teardown, or the actual provisioning workload. The earlier extended
test's reconnect timeout remains an open reliability limitation; successful
short tests do not resolve it.
