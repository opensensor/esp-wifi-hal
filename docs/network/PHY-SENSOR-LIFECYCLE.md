# C3/S3 sensor lifecycle in Rust

The temperature sensor archive member now has source implementations for its
remaining allocated functions and its five-row attribute table. This builds on
the [measurement helpers](PHY-TEMPERATURE-IMPLEMENTATION.md). The source also
handles the sensor shutdown wrapper. Full RF initialization, calibration,
tracking cadence and the remaining ROM callbacks retain their existing policy.

## Replacement and dependency boundary

| Source suffix (`__opensensor_tsens_`) | C3 original | S3 original |
| --- | --- | --- |
| `power` | `phy_set_tsens_power` | `phy_set_tsens_power` |
| `init` | `rom2_tsens_read_init1` | `tsens_read_init_new` |
| `code` | Retained ROM implementation | `ram_tsens_code_read` |
| `temp_to_power` | `rom2_temp_to_power1` | `ram_temp_to_power` |
| `get_init` | `get_temp_init` | `get_temp_init` |
| `xpd` | `phy_xpd_tsens` | `phy_xpd_tsens` |
| `attribute` | `phy_tsens_attribute` | `phy_tsens_attribute` |

The [production module](../../esp-wifi-hal/src/phy_lifecycle.rs) uses strong
linker assignments through the existing HAL build script. These redirect
same-member calls, external references and installed callbacks. Removing all
live sensor functions also eliminates C3's local `.LANCHOR0` references to the
old table; redirecting only the global table name would leave those references.
The source table retains the exact 30 bytes and explicit two-byte alignment.

`phy_xpd_tsens` belongs to a shared `phy_api.o` IRAM input, rather than
`phy_tsens.o`. Its original bytes remain in that shared input while other
routines use it. The audit reports this retained allocation separately from
the source routing. The source shutdown implementation and its literal loads
reside in IRAM and make no calls into flash.

This milestone does not replace C3's ROM sensor-code callback or either chip's
ROM code-to-temperature conversion and analog I2C callbacks. Initialization
still obtains the original ROM function table. `phy_param`, `g_phyFuns`, RF
startup/wakeup, register backup and the wider calibration routines remain
dependencies. Dormant archive functions that were already discarded are not
counted as new removals.

## Register and state behavior

Power control is intentionally chip-specific. C3 updates bit 22 of
`0x60040058` using the argument's low bit. S3 updates bits 22 and 23 of
`0x60008850` when the argument's low byte is nonzero. Both preserve the other
register bits. Shutdown reads the byte at C3 `phy_param + 0x31f` or S3 `+0x2a2`,
turns sensor power off only when that byte is zero, and always stores one.

C3 initialization optionally writes the DAC through table slot `0x1bc`,
preserving table load, slot load, attribute read and callback order. It then
updates `0x600c0014`, `0x600c001c` and `0x6004005c`, and enables sensor power.
Both arguments are full register values. A zero first argument leaves the
unused index unrestricted; a nonzero first argument requires an index in
`0..4`. Other used indexes assert. This is a deliberate input-domain restriction:
the machine instructions multiply the full register with wrapping arithmetic,
so some large unsupported indexes can wrap back onto table bytes. The source
does not preserve those aliases or out-of-object accesses.

S3 initialization ignores its argument registers. It updates `0x60008034`,
performs two separate read/modify/write operations on `0x60008904`, enables
power, and clears bit 24 of `0x60008850`. Its sensor-code reader sets and clears
bit 24 with separate register reads, then reads again and returns the low byte.
The source preserves these fresh volatile accesses and the generated Xtensa
memory barriers. There are no added polling loops or delays.

`get_temp_init` measures before reading calibration and tracking state. C3
calls the existing source outer measurement directly; S3 loads slot `0x258`
from the current table. C3 uses both full-width flags, while S3 ignores the
first flag and narrows the second to eight bits. The two chips copy different
halfword fields, and helpers may change the state before those reads. The
instruction comparisons cover this order and those mutations.

Temperature-to-power conversion first narrows the wrapping difference to a
signed 16-bit value. It preserves the following arithmetic, including behavior
outside ordinary room-temperature operation:

| Chip/mode | Positive difference | Nonpositive difference | Return register |
| --- | --- | --- | --- |
| C3, mode nonzero | Divide by 4 | Divide by 5 | Sign-extended low byte |
| C3, mode zero | Divide by 6 | Divide by 4 | Sign-extended low byte |
| S3, mode ignored | Divide by 5 | Divide by 4; decrement if the quotient's signed low byte is below -12 | Zero-extended low byte |

Signed division truncates toward zero. In particular, S3's adjustment tests
the wrapped byte, not the full quotient. The source preserves that distinction.

## Verification

The [independent original-instruction oracle](tests/phy-lifecycle-oracle/README.md)
pins the previous temperature milestone's ELF/function bytes and executes only
the selected routines. Opaque measurement and I2C callbacks can change state,
the table generation and sensor registers. Dynamically changing register-read
values expose accidental reuse of a previous read.

The production Rust matches all 562,184 C3 and 569,768 S3 cases at optimization
levels 0 and 2. Each chip's cases include 524,288 temperature-to-power cases:
all signed-16 differences with mode flags 0, 1, 256 and `UINT32_MAX`, then the
same differences with four full-register bases. Remaining cases cover all
byte flags, noncanonical argument values, state updates and MMIO ordering.
Only sensor-code and temperature-to-power APIs have compared return values;
incidental registers left by void routines are not source API contracts.

```sh
sh docs/network/tests/run-phy-lifecycle.sh
python3 docs/network/tests/test_audit_phy_lifecycle.py
python3 -O docs/network/tests/test_audit_phy_lifecycle.py
python3 docs/network/tests/audit_phy_lifecycle.py \
  --elf "$ELF" --map "$MAP" --label sensor-source --stage lifecycle
```

The `temperature` audit stage requires the previous milestone's source helpers
and retained vendor sensor lifecycle. The `lifecycle` stage additionally checks
all new function/data aliases, the exact source table, and zero allocated input
from `phy_tsens.o`, including mergeable data. Both retain the earlier source
printf, wrapper, dispatcher and no-`libpp.a` gates. Alias `ST_SIZE` may be zero
or retain a vendor size; the source body's ownership and size are checked
independently.

The [device comparison](PHY-SENSOR-LIFECYCLE-VALIDATION.md) records the tested
images, full-calibration output, shutdown/wakeup state, installed callbacks,
RX recovery and WPA2 traffic. These tests do not establish environmental RF
performance or resolve the previously observed intermittent packet losses.
