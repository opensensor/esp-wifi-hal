# C3/S3 PHY tracking

The C3 and S3 builds replace every allocated input from `phy_track.o` with
[Rust](../../esp-wifi-hal/src/phy_track.rs), retaining seven C3 and eight S3
entry names through strong linker aliases. This follows the
[analog-calibration replacement](PHY-ANALOG.md) and leaves eight allocated
vendor PHY members in the tested station images.

The replacement preserves the existing tracking dispatcher and cadence.
It covers frequency-busy polling, ULP setup/tracking, PLL tracking, power
tracking and voltage offset, plus C3 RF calibration tracking and S3's two
radio-specific power wrappers. PLL correction, gain programming, calibration
internals, ROM analog access and vendor state remain dependencies.

## Observable behavior

- Busy polling reads bit 31 of `0x6000e168` until clear. Immediate idle has no
  delay; observing busy adds one 50-us delay after it clears. The production
  loop has no timeout, matching the original.
- ULP setup preserves raw 32-bit callback transport and ordered byte stores.
  Tracking narrows the temperature difference to signed 16 bits, uses signed
  division by six for negative values and a shift by three otherwise, then
  preserves the clamp callback and signed comparison before byte narrowing.
- PLL tracking preserves the signed threshold, reentrancy byte, enter/exit
  callbacks, hardware wait, correction helper, fresh temperature reads and
  optional ULP tracking. S3's debug path retains its extra masked analog read.
- Power tracking preserves radio/mode baseline selection, both distance
  checks, chip-specific read order, signed narrowing, gain callbacks and
  original logging arguments. S3 narrows public arguments to bytes; C3 keeps
  full words. The existing temperature-to-power helper is called through its
  linker alias so LTO preserves the boundary among volatile accesses.
- Voltage offset preserves the completion flag, 3300-mV branch threshold,
  two conversion callbacks, packed state word and fresh final flag read.
- C3 RF calibration retains its AGC callbacks, TX-DC buffer arguments,
  gain reapplication and saved temperature. S3 radio wrappers retain their
  callback-table indirection.

Parameter accesses are volatile. Table and slot reads remain separate where
state reads intervene. Callbacks are not assumed pure; tests inject mutations
and arbitrary return words. Debug calls retain the pinned format strings and
integer argument order. Source entry points remain in flash. These contracts
do not assert identical stack layout, instruction counts or cycle timing.

## Verification

The [original-instruction oracle](tests/phy-track-oracle/README.md) checks
483,238 cases against production Rust at O0 and O2. It covers exhaustive
low-halfword axes, signed edges, chip argument widths, branch thresholds,
callback replacement and mutation, logging and nested helpers. Thirty focused
oracle tests and the full allocation regression suite run in CI.

Native checks compare emitted code in four source profiles per chip against
476 C3 and 544 S3 diagnostic cases. The ownership audit composes earlier
station gates and rejects any allocated tracking input, including literals,
data and excluded mergeable strings. Source bodies and aliases are checked
separately because alias sizes may be stale.

The common lifetime probe records entry points, installed callbacks and state
from normal initialization. It calls only the already-completed voltage-offset
path and verifies unchanged flags and packed state. It does not deliberately
run PLL/ULP/power adjustments or alter the dispatch period. Host/native models
cover those branches; room-temperature board trials do not exercise every RF
condition. See the [paired device report](PHY-TRACK-VALIDATION.md).

This work builds on the initial local Qwen3.8-flash-next / closed-source
re-framework reconstruction, followed by manual source correction,
instruction comparison and device validation. It is not a claim of RF or
analog equivalence. Packet-loss and timing investigations remain open, along
with other temperatures, sleep/coexistence and long-duration testing.
