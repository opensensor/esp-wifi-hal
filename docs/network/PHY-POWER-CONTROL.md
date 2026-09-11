# C3/S3 RAM power-control dispatcher inventory

This inventory identified `ram_tx_pwctrl_background`, the routine then
reached by the [source TX wrapper](PHY-WRAPPERS.md). On both chips it
reads vendor state and dispatches temperature, power and PLL tracking calls.
Its own body contains no direct MMIO accesses or vendor-state stores. This
supports replacing the dispatcher while retaining its analog helpers; it does
not support removing calibration or changing when tracking runs.

This is a static review of the published `esp-wifi-sys` 0.2.0 PHY archives and
the exact combined station images from the [previous milestone](PHY-SOURCE-VALIDATION.md).
It records the original contract rather than an implementation or device result.
The subsequent [Rust dispatcher milestone](PHY-DISPATCHER.md) implements this
boundary, retaining the analog helpers and the driver's `(1, 0)` arguments.

## Evidence identity

The [machine-readable inventory](phy-power-control-inventory.json) records
complete archive, extracted member, linked ELF, ROM reference and relevant
source SHA-256 values, plus bounded function instruction hashes. Both selected
functions belong to `phy_track.o`.

| Item | C3 | S3 |
| --- | --- | --- |
| `libphy.a` SHA-256 | `94c0e05bb4d5a79917a382496c108fff4ed96f784575550a6d931caaca104aa9` | `29dcc18a035801bd41486d5d59f3caeb62f8ed153533c488828bffef1abb99fd` |
| Linked function address / body bytes | `0x4203cc1c` / 122 | `0x4203a3e4` / 78 |
| Vendor `phy_param` size | 848 bytes | 740 bytes |
| ROM reference | `esp32c3_rev3_rom.elf` | `esp32s3_rev0_rom.elf` |

The source review starts at HAL revision
`99e6617b7af6c126eaa7eb7b3c40dacc82de93e2`. Its sys dependency,
`73add8985cec3b7582e6df80a4273022deb844b0`, retains these published PHY
archives byte-for-byte. Function instruction hashes refer to the named linked
images; relocated bytes need not match a different link. No proprietary
object, firmware, calibration or packet bytes are included here.

## Complete dispatcher contracts

All offsets below are bytes. `table_call(offset, ...)` means loading the
**current** `g_phyFuns` pointer, reading its function pointer at that offset,
and invoking it with the chip's C ABI. Each occurrence reloads the table.
`read8` and `read32` describe the original access widths, not an inferred
Rust struct layout. Stack and ABI bookkeeping are omitted.

C3 control flow:

```text
token = table_call(0x184)
gate_a = read8(phy_param + 0x320)
gate_b = read8(phy_param + 0x31f)
if (gate_a | gate_b) == 0:
    rom1_tsens_temp_read()
    rom_wifi_track_tx_power(input0, input1)   # direct ROM veneer 0x40001c2c
    if read8(phy_param + 0x09c) != 0:
        ram2_rfpll_cap_track(read8(phy_param + 0x09b))
    if read8(phy_param + 0x216) != 0:
        rfcal_track(read8(phy_param + 0x09b), 20)
tail_call_current_table(0x188, token)
```

The two gate loads occur in the displayed order. The RF flag is read after
the optional PLL call, and its argument byte is read again. An implementation
must not cache those values before calling a helper. The dispatcher preserves
the incoming argument registers; its existing outer C ABI supplies two
unsigned bytes. Registers outside that valid input domain are not additional
supported inputs.

S3 control flow:

```text
input0 = input0 & 0xff
input1 = input1 & 0xff
token = table_call(0x160)
gate = read32(phy_param + 0x2a0)
if (gate & 0xffff0000) == 0:
    table_call(0x258)                        # installed temperature callback
    table_call(0x28c, input0, input1)         # installed TX-power callback
    if read8(phy_param + 0x09c) != 0:
        rfpll_cap_track(read8(phy_param + 0x09b))
table_call(0x164, token)
return
```

S3 uses one aligned 32-bit load and `bany` with `0xffff0000`. The selected
bytes are at `+0x2a2` and `+0x2a3`, but replacing the original load with two
byte accesses would change its memory-access contract. Its lower 16 bits do
not affect the branch. The two input `extui` operations precede the enter
call. Outgoing arguments use the Xtensa call8 register window. There is no
C3-style second RF-calibration branch.

Every normal path calls enter once and exit once, including the gate-closed
path. Exit receives the complete 32-bit token returned by enter. The token
must not be narrowed to a Boolean or reconstructed from a new lock operation.
The dispatcher ignores the temperature/tracking return values; their state
and analog effects remain required.

## Callback and analog boundaries

The installed S3 temperature slot `+0x258` targets `ram_tsens_temp_read`;
the TX slot `+0x28c` targets `ram_wifi_track_tx_power`. That latter wrapper
narrows its inputs and calls slot `+0x268` with `(0, input0, input1)`, whose
installed target is `ram_txpwr_cal_track`. Retain this chain. The table is
reloaded before each S3 indirect call, so a source implementation must not
resolve all callbacks just once at entry.

C3 calls its RAM temperature helper and ROM TX-power veneer directly. Its
installer also puts `rom1_tsens_temp_read` in table slot `+0x27c`, but the
selected dispatcher does not use that slot. The chip-specific dispatch paths
are not interchangeable.

Both temperature helpers call `phy_get_tsens_value` and store a halfword at
`phy_param + 0x92`. This observable side effect is one reason that ignoring
their return values does not make their calls optional. The retained PLL
helpers use temperature state at `+0x92` / `+0x94` and further busy/calibration
state: C3 includes `+0x321`, while S3 includes `+0x2a4` and `+0x2a8`.
C3's retained `rfcal_track` also reads `+0x214` and uses the supplied threshold
20. These helpers reach hardware-frequency, AGC and calibration operations;
their algorithms have not been fully reconstructed by this audit.

The enter/exit table slots require particular care:

| Chip | Enter / exit slots | Default targets in the ROM reference |
| --- | --- | --- |
| C3 | `+0x184` / `+0x188` | `rom_enter_critical_phy` / `rom_exit_critical_phy` |
| S3 | `+0x160` / `+0x164` | `rom_enter_critical_phy` / `rom_exit_critical_phy` |

In these ROM reference files, enter returns zero and exit simply returns.
The inspected `phy_get_romfunc_addr` installer does not replace these two
slots. **Live table values were not read from a device.** This evidence is
insufficient to claim the runtime path has no locking, or to hardcode no-op
callbacks in a replacement.

These slots are distinct from the named `phy_enter_critical` and
`phy_exit_critical` imports. Relocations to those names in the same archive
member belong to `phy_param_track`, not this dispatcher. At the reviewed
source revision, C3's named imports use the vendored adapter's `ESP_PHY_LOCK`
through linker `PROVIDE` aliases; S3 has strong driver definitions using
`critical_section::acquire` / `release`. Substituting either named pair for
the table dispatch would change the original contract.

## Original implementation proposal and acceptance gates

Implement only the dispatcher behind the current source wrapper. Keep the
initialized vendor parameter object, function table, direct ROM entry and
all selected analog helpers. Use raw pointers rather than creating a Rust
reference to mutable vendor state, preserve the observed load widths and
ordering, and inspect the compiled target instructions. Changing periodic
tracking cadence, critical-section policy, transmit power or calibration is
outside this boundary.

Before enabling such a replacement, the next implementation needs:

- An independent oracle derived from the original instructions, with opaque
  helper boundaries that record calls, arguments and state reads. Compare the
  actual production source against that oracle. Test hooks must not become
  production replacements for calibration.
- All 65,536 valid argument pairs; all C3 gate-byte combinations; all S3
  upper-halfword combinations with varying lower halfwords. Require the S3
  single 32-bit access, not merely the same Boolean branch result.
- Optional-flag values including 0, 1, 128 and 255; every value of the argument
  byte at `+0x09b`; token cases including `0`, `1`, `0x80000000` and
  `0xffffffff`. Require exact enter/exit pairing and unchanged token forwarding.
- Adversarial hooks that change later flags, argument bytes and the table
  pointer between calls. In particular, C3's PLL hook must be able to change
  the subsequent RF flag and argument, and S3's temperature hook must be able
  to change the following TX callback. Check that the dispatcher itself
  performs no vendor-state writes.
- Final C3/S3 ABI and linker-map review: the old dispatcher input section is
  discarded, while required helpers, `phy_param` and the callback table remain.
  Use [SHF_ALLOC-based input accounting](tests/PHY-ALLOCATION-AUDIT.md), including
  literals and `COMMON`. The 122/78-byte function bodies alone do not predict
  total vendor allocation or firmware-size changes.
- Paired device comparisons using the same configuration and unchanged analog
  helpers: fresh PHY initialization, the existing ABI/RX probe, guard drop and
  wakeup, WPA2/DHCP and station traffic on both chips. Retain failures and
  investigate packet losses separately; a compile or instruction oracle cannot
  establish RF equivalence.

This boundary offers further source visibility into tracking decisions. It
does not yet remove another PHY member, justify eliminating the analog
helpers, or explain the outstanding S3 packet losses.
