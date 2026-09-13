# C3/S3 PHY feature member replacement

`esp-wifi-hal/src/phy_feature.rs` supplies four selected helpers from
`phy_feature.o`. Strong linker assignments remove the complete allocated
member in the compared images, while the original archives remain unchanged.

| Entry | Source placement | Retained dependency |
| --- | --- | --- |
| `phy_dig_reg_backup` | IRAM | Chip-specific ROM digital register backup |
| `phy_freq_mem_backup` | IRAM | Chip-specific ROM frequency memory backup |
| `phy_set_most_tpw` | Flash | C3 gain helper / S3 gain callback |
| `phy_11p_set` | Flash | Analog I2C write callback |

ROM bindings remain absolute: C3 digital `0x40001c30`, frequency `0x40001c20`;
S3 digital `0x40006408`, frequency `0x400063d8`. S3's ROM symbol sizes may
describe discarded archive implementations and are not allocated body sizes.

## Preserved behavior

The backup adapters preserve the buffer pointer and forward the mode argument
unchanged on C3 or narrowed to its low byte on S3. Digital backup forwards the
ROM result; frequency backup has a void interface. The native entries and
required S3 literals stay in IRAM. The ROM implementations remain dependencies.

Power adjustment stores the low argument byte at `phy_param+0x98`, reads the
channel byte at `+0x1f2` and passes `(channel, 0)` to gain adjustment. C3 uses
the retained `ram1_wifi_set_tx_gain` directly. S3 loads the callback table
before the parameter store, reads slot `0x264` from that snapshot, then reads
the channel and calls the selected callback.

Channel-mode configuration stores the two low argument bytes at `+0xef` and
`+0xf0`. C3 branches on the full arguments; S3 first narrows both to bytes.
It replaces bits 2–4 of `0x6002600c` with zero when disabled, four when enabled
with the second argument zero, or five otherwise. It then sets bit 5 of
`0x6001c030` when disabled, or clears it when enabled, preserving other bits.

Enabled mode reads parameter `+0x166` once and computes
`min(63, ((value + 56) * 103) / divisor - 8)`, with divisor 100 when the second
argument is zero or 50 otherwise. It passes that value to eight analog writes,
registers `4, 5, 12, 13, 6, 7, 14, 15`, in that order. Disabled mode rereads
`+0x167` for each of the first four writes and `+0x168` for each of the last
four, so callback mutations remain visible. Block is 103; host is one on C3
and zero on S3. The callback slot is `0x1b4` on C3 or `0x190` on S3.

C3 loads its initial table before the parameter stores and its initial
callback before MMIO. S3 resolves the first callback after MMIO and the
enabled-mode calculation. Both reload the table for every subsequent call;
disabled-mode parameter reads precede the corresponding slot load. The source
preserves these differences instead of caching one callback for the loop.

## Validation

The [original-instruction oracle](tests/phy-feature-oracle/README.md) compares
the production logic against **414,480 cases at O0 and O2**. It checks argument
widths, ROM routing, helper arguments, ordered register/parameter accesses,
callback-table snapshots, callback mutations and mode arithmetic. Native
review separately checks ABI, aliases, IRAM entries and literal placement.

```sh
sh docs/network/tests/run-phy-feature.sh
python3 docs/network/tests/test_audit_phy_feature.py
python3 -O docs/network/tests/test_audit_phy_feature.py
python3 docs/network/tests/audit_phy_feature.py \
  --elf /path/source-sta_smoke.elf --map /path/source-sta_smoke.map \
  --label source --expect-feature source
```

The feature audit explicitly allows the earlier basic audit's power dependency
to become a real source body with the correct alias and no vendor overlap.
The standalone basic audit still requires original power-helper ownership.
The composed lifecycle gate similarly checks the real IRAM digital-backup
source body; earlier standalone lifecycle/API gates retain vendor ownership.
The new audit requires complete feature-member absence, preserves the ROM
bindings and checks C3's retained gain helper ownership.

The lifetime probe records entry addresses and existing power/mode bytes
inside the normal PHY guard. Guard teardown/wakeup exercises the existing
backup flow. The probe does not issue additional power or channel-mode writes
or change RF tracking cadence. Host mode coverage does not establish unusual
mode RF behavior. Device results and remaining limitations are recorded in
the [comparison report](PHY-FEATURE-VALIDATION.md).
