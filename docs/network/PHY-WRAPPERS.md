# Source replacements for two PHY wrappers

C3 and S3 now bypass the vendor `tx_pwctrl_background` wrapper and implement
`phy_bbpll_en_usb` in Rust. The RAM tracking callee, parameter data, calibration
and RF configuration remain vendor code. This is a small integration milestone,
not an open PHY implementation or a change to transmit power policy.

## Original contracts and integration

| Wrapper | C3 contract | S3 contract |
| --- | --- | --- |
| `tx_pwctrl_background(u8, u8)` | Tail-call `ram_tx_pwctrl_background` with both argument registers unchanged | Narrow both arguments to eight bits, then call the RAM routine once |
| `phy_bbpll_en_usb(bool)` | Store one byte at `phy_param + 0x323`; data object size 848 bytes | Store one byte at `phy_param + 0x2a6`; data object size 740 bytes |

The byte-store instructions accept arbitrary low-byte register values, but the
open adapter's existing C `bool` ABI only permits zero and one. The Rust source
retains that valid-input boundary. Its raw pointer avoids creating a reference
to the vendor-owned parameter object. Volatile byte access prevents combining
this write with neighboring state; S3 emits the compiler's `memw` ordering
instruction before the store.

The driver's wrapper calls the retained RAM routine directly. It changes no
transmission cadence, callback table, argument values or channel/AGC sequence.
In particular, the direct AGC operations still use `0x6001c038`; internal RAM
AGC callbacks keep their different `0x6001c034` contract.

USB enable is called internally by `esp-phy`, so replacing only a driver FFI
declaration would leave the original body linked. A second same-name exported
symbol would conflict with other needed functions in `phy_api.o`. Instead,
[`vendor/esp-phy`](../../vendor/esp-phy/OPENSENSOR.md) contains the published
0.2.0 adapter with a small explicit source change. Its calibration path invokes
the source helper under the original USB/chip configuration and PHY state
lock, immediately where the vendor call occurred before `register_chipv7_phy`.
Other chips keep the original FFI path. Guard lifetime, calibration selection,
backup, shutdown and wakeup paths are unchanged.

The vendored adapter pins both chip-specific `esp-wifi-sys` versions to
`=0.2.0`. Updating their private data layout requires reviewing these offsets
again. Both the direct driver dependency and the examples' transitive patch
select the same adapter; the lockfiles preserve all other dependency versions.

## Validation

Run the actual production-source boundary tests with:

```sh
sh docs/network/tests/run-phy-wrappers.sh
```

For each chip at optimization levels zero and two, the tests exercise all
65,536 valid argument pairs against an external RAM-call recorder, requiring
exactly one ordered call per invocation. USB tests cover both Boolean values
across 256 full-parameter patterns and repeated enable/disable transitions,
checking every other byte remains untouched. The independent original
instruction evidence and fail-closed replay are in
[`phy-wrapper-oracle`](tests/phy-wrapper-oracle/README.md). Neither harness
models analog calibration or substitutes a generated implementation as its
reference. The existing C/Rust HAL regression suite also passes.

Both `sta_smoke` crosslinks pass with dummy credentials, `ESP_LOG=info`, one
configured cycle and the `esp32c3,foa-smoke` / `esp32s3,foa-smoke` features.
[`phy-wrapper-builds.json`](phy-wrapper-builds.json) identifies the exact
build-only ELFs and maps. These probes still use the original printf archive
and have not run on hardware.

| Static result | C3 | S3 |
| --- | ---: | ---: |
| Allocated `libphy.a` input bytes | 35,593 | 33,218 |
| Allocated input sections | 165 | 164 |
| Allocated archive members | 18 | 18 |
| Retained `ram_tx_pwctrl_background` body | 122 bytes | 78 bytes |
| Original wrapper symbols/allocated sections | absent | absent |

Relative to the [earlier dependency inventory](PHY-DEPENDENCIES.md), the
removed vendor inputs total 12 bytes on C3 and 32 bytes on S3, including the
S3 literal. This measures vendor allocation removed, not a total firmware-size
reduction: source instructions now occur in the Rust caller. Disassembly also
confirms the byte store occurs before calibration and that TX calls the RAM
callee using the expected C3 argument registers / S3 call8 register window.

Fresh PHY initialization, USB serial continuity, station traffic and the
existing RX recovery/lifetime checks must be recorded for the integrated
device images. Station reconnect cycles keep the PHY guard alive; they do not
by themselves validate full shutdown and wakeup. No packet-loss improvement
is claimed for these wrappers.
