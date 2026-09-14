# C3/S3 RF PLL and channel helpers

C3 and S3 replace every allocated input from `phy_rfpll.o` with
[Rust](../../esp-wifi-hal/src/phy_rfpll.rs), retaining 16 C3 and 18 S3 entry
names through strong linker aliases. This follows the
[tracking replacement](PHY-TRACK.md) and leaves seven allocated vendor PHY
members in the tested station images. It covers PLL restart, SDM programming,
frequency arithmetic, offset updates, capacitor correction/calibration and
channel selection. ROM, analog access, gain programming, calibration state and
hardware-frequency memory helpers remain dependencies.

## Preserved behavior

- PLL selection uses 26/32/48 MHz for C3 selectors 1/2/3, with a 40 MHz fallback.
  S3 uses 26/32 MHz for selectors 1/2 and 40 MHz otherwise. The selector uses
  its low byte. Signed division truncates toward zero; intermediate arithmetic
  wraps at 32 bits and each output byte is narrowed before computing the next.
- SDM programming reloads each of the three buffer bytes after the preceding
  callback. Table loads, buffer reads and slot loads retain their order.
- Calibration completion waits 20 microseconds before each masked read. Any
  nonzero callback word ends the wait. After exactly 100 unsuccessful reads,
  the original timeout message is printed and the function returns.
- Frequency correction compares a signed halfword, then updates all 85 entries
  with their original MMIO widths and read/modify/write order. The sum is not
  remasked after adding the correction to the low 24 bits.
- Capacitor reads add both callback results before halfword narrowing. C3's
  capacitor write preserves the full shifted high word; S3 narrows to 16 bits.
  Correction preserves the ten-attempt bound, transition-specific adjustment,
  mutable special/saved state, six debug arguments and memory-update callback.
- Initial capacitor calibration scans both directions, preserving a shared
  success count, 16-bit sum, early exit conditions and packed return. S3 uses
  its installed capacitor-write callback; C3 calls the selected entry directly.
- Channel helpers preserve critical-section tokens, AGC callbacks, state widths,
  RF enable/disable order, gain-buffer pointers and the eight-argument gain
  helper. S3 has signed byte channel transport and an extra register update
  when the channel changes. C3 retains its seven-argument mode callback.

Public entry points remain in flash. Parameter and MMIO accesses are volatile.
Separate table and slot reads preserve intervening state accesses. Helper calls
remain explicit boundaries; the code does not add calibration work to the
tracking schedule or change the existing timeout.

## Verification

The [instruction oracle](tests/phy-rfpll-oracle/README.md) checks 143,805 C3 and
145,305 S3 cases against production Rust at O0 and O2, reaching all 754 C3 and
707 S3 recorded instructions. Thirty focused oracle tests check specific
contracts and malformed evidence. The allocation gate composes all preceding
source gates and rejects any remaining RF PLL member input, including data,
literals and excluded mergeable strings. The full allocation suite has 211
tests and also runs with Python assertions disabled.

Native emitted-code comparisons cover four firmware profiles per chip, with
760 C3 and 854 S3 cases per profile: 6,456 case executions across 136 compiled
entry bodies. These check ABI argument transport, stack-passed arguments,
callback/state ordering and pointer contents after optimization. The common
lifetime probe checks eight pinned arithmetic vectors with buffer canaries,
then observes entry points, callbacks and state after normal initialization.
It does not start another calibration or program an RF register.

These are bounded comparisons, not a Cartesian proof, an RF accuracy claim or
an instruction-cycle timing claim. Normal initialization and station traffic
exercise only the board conditions represented in the
[paired device report](PHY-RFPLL-VALIDATION.md). Packet-loss investigation,
other temperatures, sleep/coexistence and long-duration testing remain open.

This work continues the initial local Qwen3.8-flash-next / closed-source
re-framework reconstruction with manual Rust correction, original-instruction
comparison and hardware validation. OpenSensor Engineering is available for
additional reverse-engineering and embedded contract work.
