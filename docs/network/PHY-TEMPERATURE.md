# Temperature reconstruction boundary on C3 and S3

The five-function boundary below is now
[implemented in Rust](PHY-TEMPERATURE-IMPLEMENTATION.md). The
[device comparison](PHY-TEMPERATURE-VALIDATION.md) records the tested images,
remaining allocations and observed retries. The baseline and proposal below
remain the evidence used to choose this boundary; the complete sensor member
and the wider PHY are still only partially reconstructed.

## Original proposal

The next source replacement targets the temperature-sensor path behind the
[open tracking dispatcher](PHY-DISPATCHER.md). This is a static inventory and
implementation plan, not a completed replacement or a new device result.
Full RF initialization, channel tuning, power/PLL tracking and ROM dependencies
remain. The earlier [dependency inventory](PHY-DEPENDENCIES.md) describes
historical images; its small wrapper candidates are already implemented.

## Current tested baseline

The [baseline inventory](phy-temperature-baseline.json) audits the ordinary
`gtk-normal-v1-sta_smoke` images from the [GTK milestone](GTK-REKEY.md).
Each previously passed two reconnects and 40/40 echoes in both directions
against the router. Those short trials do not resolve the documented longer
traffic losses or establish temperature-range coverage.

| Allocated input, excluding mergeable strings | C3 | S3 |
| --- | ---: | ---: |
| Remaining `libphy.a` | 35,471 bytes | 33,160 bytes |
| Remaining PHY members | 18 | 18 |
| `phy_tsens.o` contribution | 578 bytes | 589 bytes |
| `libpp.a` | 0 bytes | 0 bytes |

These are live input allocations, including literals and data, not archive
file sizes or predicted firmware savings. Link relaxation can change the S3
total between builds; the older dispatcher report's 33,156-byte total remains
specific to its image. The current audits pass the source printf, wrapper and
dispatcher gates. Temperature, RF calibration, PLL helpers and vendor state
remain allocated.

The images were built in a checkout at `b2418a0` with changes subsequently
published in HAL `37303f7`; all 44 recorded source-file hashes per chip match
that published revision. FoA is `2143118`, including the M4 retry and GTK fixes.
The inventory keeps checkout identity, source hashes, ELF/map hashes, observed
archive hashes and selected function hashes separate.

## First boundary: periodic temperature measurement

| Role | C3 | S3 |
| --- | --- | --- |
| Store temperature for tracking | `rom1_tsens_temp_read` | `ram_tsens_temp_read` |
| Forward measurement | `phy_get_tsens_value` | `phy_get_tsens_value` |
| Read and adjust sensor range | `tsens_temp_read1` | `ram_tsens_temp_read_new` |
| Decode DAC setting | `tsens_dac_to_index` | `tsens_dac_to_index` |
| Select DAC range | `tsens_dac_cal1` | `tsens_dac_cal_new` |

The outer routine returns the measurement and stores its low 16 bits at
`phy_param + 0x92`. The inner routine reads the sensor DAC through a callback,
decodes its low nibble, stores an index byte at `+0xaa`, obtains a measurement
through callbacks, applies range adjustment and returns the original
measurement. Preserve fresh state/table reads across those calls.

The corresponding callback offsets differ:

| Call in the read/range path | C3 table offset | S3 table offset |
| --- | ---: | ---: |
| Read DAC register `(105, 0, 6)` | `0x1ac` | `0x188` |
| Obtain sensor code | `0x208` | `0x1e4` |
| Convert using signed attribute byte | `0x218` | `0x1f4` |
| Write DAC field `(105, 0, 6, 3, 0, value)` | `0x1bc` | `0x198` |

These identify observed dispatch slots, not proven live callback targets.
Resolving the initializer and ROM table is part of the implementation evidence.
The analog callbacks and the vendor attribute table can remain opaque during
the first comparison.

Two details require explicit oracle coverage:

- DAC codes `5, 7, 15, 11, 10` map to indexes `0..4`; other values return
  index 5, while the linked attribute table contains only five six-byte rows.
  Establish the supported hardware/caller domain before indexing in Rust.
  Neither inventing a sixth row nor silently clamping is an evidenced fix.
- The S3 range selector sign-extends the temperature to 16 bits and narrows
  its index to eight bits. C3 compares its incoming argument registers
  directly. Confirm the C ABI at every caller instead of assuming identical
  behavior outside its valid domain.

S3 linear disassembly also consumes padding after a return and misdecodes the
block starting at `tsens_dac_cal_new + 0x25`. Restarting at the branch target
`0x4203be09` in this exact ELF resolves the block. Extract reachable basic
blocks for the oracle; do not feed the linear decode into reconstruction as
valid instructions.

## Acceptance and following work

1. Resolve callers, table installation and reachable instructions from the
   pinned archives/images. Compare production Rust against an independent
   original-instruction oracle: access widths/order, signed values, range
   edges, callback replacement and measurement return/store behavior.
2. Cross-build both chips and verify ABI, code placement and linker routing,
   including the installed S3 callback and C3 direct call. Prove the selected
   vendor bodies are absent. The archive member also supplies other routines;
   replacing a call site alone does not remove that member.
3. Compare vendor and source images with the current FoA fixes held constant:
   initial calibration, sole PHY guard release/wakeup, RX recovery,
   WPA2/DHCP, router echoes and GTK/broadcast/multicast traffic. Keep loss and
   timing measurements alongside the existing baseline, including failures.
4. Complete the remaining sensor initialization, power and temperature-helper
   routines, with their tables and callers, before claiming `phy_tsens.o`
   removed. The reported 578/589 bytes cover that whole member, not just the
   five functions in the first boundary.
5. Continue into I2C/PBUS/register helpers, then PLL and RX/TX calibration,
   using their actual dependency graph to choose each replacement. Full
   `register_chipv7_phy` and channel initialization follow those foundations.

Keep periodic tracking cadence and calibration policy fixed during these
comparisons. A host trace match or short station run alone does not establish
RF behavior across temperature, channels and operating conditions.

Reproduce each baseline allocation with the existing
[allocation auditor](tests/PHY-ALLOCATION-AUDIT.md):

```sh
python3 docs/network/tests/audit_phy_allocations.py \
  --elf "$ELF" --map "$MAP" --label gtk-normal-v1-sta_smoke \
  --expect-printf source --expect-phy-wrappers source \
  --expect-phy-dispatcher source --exclude-merged-strings
```
