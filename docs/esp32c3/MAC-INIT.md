# ESP32-C3 Rust MAC initialization

C3 now initializes the MAC in Rust, including the eight helper bodies formerly
pulled from `libpp.a`. The station link map has **no allocated `libpp.a` sections**.
PHY calibration/channel/power code and ROM routines remain external. This is a
partial Wi-Fi deblob; it does not replace the PHY or the complete vendor SDK.

The implementation is in `esp-wifi-hal/src/c3_mac.rs`, called after existing
power, clock, PHY and ROM OS-adapter setup. It retains the order and widths of
volatile 32-bit register accesses. It installs a zero RX base so the Rust driver
can supply its owned descriptor list. Bluetooth coexistence is disabled by the
existing OS adapter; active Bluetooth scheduling is outside this implementation.

## C3-specific evidence

The analysis covered the C3 IDF 5.4 HAL and the actual esp-wifi-sys-esp32c3 0.2.0
HAL linked into the tested Rust baseline. Five archive members differ bytewise;
260 bounded instruction-derived transaction cases agree between those versions
and the Rust implementation. Tests include full init, eight helper bodies,
four initial register patterns, priority masking, and RTC enable/calibration
boundaries. The [public host tests](tests/README.md) need only stable Rust.

Two RX range constants differ from S3: the low 20 bits at `0x60033c5c` are
`0xe0000`, and those at `0x60033c60` are `0x80000`. Descriptor high-address
configuration remains `0x3fc00000`. The original C3 RTC helper branches on the
full incoming register, whereas the S3 instructions first truncate to a byte;
the actual init caller supplies 1. No explicit RISC-V FENCE occurs in the
audited original functions. Host traces model register storage and explicit
callbacks, not bus ordering, hardware side effects, DMA or interrupt timing.

## Hardware checks

The preceding vendor-init Rust milestone passed three WPA2/DHCP cycles with
60/60 gateway replies and 58/60 host replies, as recorded in
[the bring-up results](validation.json). The current Rust-init experiments and
failures are retained separately in [mac-init-validation.json](mac-init-validation.json).

The final low-level smoke image received eight frames (two OFDM), preserved an
unread completed buffer while nine others were held, exhausted all ten buffers,
recovered after reverse-order returns, completed OFDM 6 Mbps TX and observed an
advancing MAC timer. This pending-buffer test verifies the exercised hardware
path. The queue fallback defect itself was reproduced by a host test; the
hardware test is not proof that this fallback executed.

| Station experiment | Connection cycles | Gateway echoes | Host echoes |
| --- | --- | --- | --- |
| Rust init, first run | Timed out before cycle 1 | None | None |
| Same image, repeated | 10/10 | 200/200 | 190/200 |
| Rust init plus queue fix, first run | Timed out before cycle 1 | None | None |
| Same final image, repeated | 10/10 | 200/200 | 185/200 |

The final host counts by cycle were 20, 14, 19, 19, 18, 19, 19, 19, 19, 19.
The larger losses in cycles 2 and 5 are unexplained; they must not be attributed
solely to the known first-ARP reply issue. The queue fix preserves a proven
software invariant, but these results do not demonstrate that it fixes the
connection timeout or improves end-to-end packet delivery.

The station test reconnects an initialized driver. It does not exercise full
Wi-Fi deinitialization on every cycle or prove cold-power-on reliability. The
intermittent connection timeout remains unexplained. Host reply losses are
reported independently; first-packet ARP behavior was reproduced separately in
smoltcp, but that does not explain every lost packet in these C3 runs.

Only the factory app slot at `0x10000` was written. The original provisioner
flash backup, bootloader and partition table remain available. The provisioner
application workload has not yet been ported. Firmware, credentials and raw
network logs are private; public evidence includes image, source and log hashes.

## Build

Use the [C3 toolchain and PAC instructions](README.md#build-and-repeat). Both
`wifi_smoke` and `sta_smoke` select the Rust sequence with feature `esp32c3`.
Host checks run in CI through `docs/esp32s3/tests/run-rust-tests.sh`, including
the 260 C3 initialization cases and the actual DMA list under both chip features.

For an extended station run, set `S3_SMOKE_CYCLES=10` in the build environment;
that historical environment variable currently controls both C3 and S3. Set
`SSID` and `PASSWORD` privately. Keep resulting station binaries private.
