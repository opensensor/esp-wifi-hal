# C3/S3 temperature measurement in Rust

The [temperature source module](../../esp-wifi-hal/src/phy_temperature.rs)
replaces the five measurement and DAC-range functions selected in the
[baseline plan](PHY-TEMPERATURE.md). The production Rust matches the independent
instruction oracle on both chips, and linked images redirect the original
symbols to source implementations. Sensor initialization, analog access,
conversion, calibration and the vendor attribute table remain dependencies.

This document records the implementation and host/link evidence. Device
results belong in [PHY-TEMPERATURE-VALIDATION.md](PHY-TEMPERATURE-VALIDATION.md);
that separate report is required before treating this as a validated hardware
replacement. These checks do not resolve earlier packet-loss or timing tails.

## Replacement boundary and linking

The five exported source symbols use the prefix `__opensensor_tsens_`:

| Source suffix | C3 original | S3 original |
| --- | --- | --- |
| `decode` | `tsens_dac_to_index` | `tsens_dac_to_index` |
| `range` | `tsens_dac_cal1` | `tsens_dac_cal_new` |
| `inner` | `tsens_temp_read1` | `ram_tsens_temp_read_new` |
| `forward` | `phy_get_tsens_value` | `phy_get_tsens_value` |
| `outer` | `rom1_tsens_temp_read` | `ram_tsens_temp_read` |

The [HAL build script](../../esp-wifi-hal/build.rs) generates a linker script
named `libesp-wifi-hal-temperature.a`, following the existing `esp-phy` approach
for propagating linker declarations to consumers. Each name has an `EXTERN`
for its source definition and a strong assignment, for example:

```ld
EXTERN(__opensensor_tsens_outer);
rom1_tsens_temp_read = __opensensor_tsens_outer;
```

This redirects external references, installed callback addresses and direct
references from the same archive member. GNU `--wrap` only redirects undefined
references: C3's retained `get_temp_init` lives in `phy_tsens.o` and directly
calls that member's `rom1_tsens_temp_read`. Wrapping only external references
would leave the original measurement chain reachable through initialization.
Strong assignments redirect that call while retaining `get_temp_init` itself.

C3's `phy_get_romfunc_addr` installs the outer routine at `g_phyFuns + 0x27c`
and the forwarding routine at `+0x210`. Its ordinary tracking dispatcher also
calls the outer routine directly. S3 installs the outer routine at `+0x258`;
its dispatcher and retained `get_temp_init` call that slot. These initializer
relocations resolve to the source symbols in the replacement images.

GNU ld on both chips and Rust's LLD on C3 were checked with the actual pinned
archive member. Full images also show the selected vendor text/literal inputs
discarded. An original alias can retain the vendor's old `ST_SIZE`, have size
zero, or be represented as an absolute linker symbol. The audit checks its
address against the allocated source body and checks input ownership separately;
an alias name or size alone does not prove removal.

## Calling convention and ordered accesses

The replacement entrypoints accept register-width values and implement the
chip's explicit narrowing. C3's decoder compares the full incoming register;
S3's decoder first keeps its low eight bits. C3's range selector compares the
full signed temperature and full index. S3 sign-extends the low 16 temperature
bits and keeps the low eight index bits. Both inner callers first mask the
DAC register value to its low nibble.

The selector first checks the current attribute row's inclusive lower/upper
bounds. If the measurement is still in that range, it returns the row's DAC
without a write. Otherwise it selects DAC `5` above 99, `7` above 79, `15`
from -9, `11` from -29, and `10` below -29, then makes one masked DAC write.
It returns the selected DAC regardless of the callback's return register.

| Operation | C3 slot | S3 slot | Native callback signature |
| --- | ---: | ---: | --- |
| Read DAC register | `0x1ac` | `0x188` | `(u8, u8, u8) -> u8` |
| Read sensor code | `0x208` | `0x1e4` | `() -> u32` |
| Convert code and signed offset | `0x218` | `0x1f4` | `(u32, i32) -> i32` |
| Write DAC field | `0x1bc` | `0x198` | `(u8, u8, u8, u8, u8, u8) -> ()` |

The DAC calls use `(105, 0, 6)` and `(105, 0, 6, 3, 0, dac)` respectively.
Their byte arguments and return type follow the official
[ESP-ROM I2C declarations](https://github.com/espressif/esp-idf/blob/67c1de1eebe095d554d281952fde63c16ee2dca0/components/esp_rom/include/esp_rom_regi2c.h).
The chip ROM API linker files alias those APIs to `rom_i2c_readReg` and
`rom_i2c_writeReg_Mask`. No public prototype was located for the code and
conversion callbacks; their register-width signatures follow the observed
callers and ROM instructions. The native adapter uses the appropriate
signature for each slot rather than calling every helper as a six-argument
function.

The inner routine stores the decoded index byte at `phy_param + 0xaa`, calls
the code helper, rereads that byte, obtains the row's signed offset, calls
conversion, rereads the index again and applies range selection. C3 loads
the code callback slot before the index store; S3 loads it after the store.
Both reload `g_phyFuns` before the signed attribute-byte read. The code and
conversion callbacks can replace the table or change the stored index, so
the source keeps these fresh reads and the original ordering.

Inner and forward return the original full conversion register, even if range
selection changes the DAC. Outer also returns that full value and stores only
its low 16 bits at `phy_param + 0x92`. Parameter, table and attribute accesses
use volatile operations with the observed widths. The pinned parameter block
is 848 bytes on C3 and 740 on S3; the attribute table requires two-byte alignment.

## Finite attribute table and supported domain

The original table contains five six-byte rows. The independently checked
official [C3 table](https://github.com/espressif/esp-idf/blob/67c1de1eebe095d554d281952fde63c16ee2dca0/components/soc/esp32c3/temperature_sensor_periph.c)
and [S3 table](https://github.com/espressif/esp-idf/blob/67c1de1eebe095d554d281952fde63c16ee2dca0/components/soc/esp32s3/temperature_sensor_periph.c)
identify the same supported DAC settings, offsets and temperature ranges:

| Index | Signed offset | DAC | Inclusive range |
| ---: | ---: | ---: | --- |
| 0 | -2 | 5 | 50 to 125 |
| 1 | -1 | 7 | 20 to 100 |
| 2 | 0 | 15 | -10 to 80 |
| 3 | 1 | 11 | -30 to 50 |
| 4 | 2 | 10 | -40 to 20 |

Those public references were checked against the clean local ESP-IDF files at
commit `67c1de1eebe095d554d281952fde63c16ee2dca0`. The production replacement
continues to use the linked vendor table; it does not substitute an IDF driver
or a new range policy.

Other decoder inputs produce sentinel 5. The source preserves that result,
then checks `index < 5` immediately before each row access. It does not clamp
the index or invent a sixth row. Crucially, the code helper runs after the
decoded index is stored and before the first row access: a helper can restore
a valid index after a sentinel result. Those cases remain supported and are
covered by the oracle. Rejecting eagerly in the decoder would change them.

An index still outside the table at a row access triggers an assertion instead
of reading beyond the object. This is deliberate behavior outside the original
valid-access equivalence domain. The current linked C3 init callers skip the
optional DAC-writing arm of `rom2_tsens_read_init1`, and S3's
`tsens_read_init_new` does not write the DAC. Analog/reset defaults and live
state therefore still require separate evidence; the five-row table does not
prove that every possible hardware nibble is supported.

## Host oracle, allocation gates and native size

The [independent interpreter](tests/phy-temperature-oracle/README.md) executes
the pinned original instructions and opaque callback effects. Production Rust
matches 366,074 C3 cases and 366,099 S3 cases at both optimization levels 0 and
2. Coverage includes every signed 16-bit temperature across the five valid
rows, decoder inputs, boundary values, full-register ABI cases, table replacement
and index mutation. Nineteen oracle tests pass with and without Python
assertions; three production-source tests per chip/optimization check the
complete case stream and invalid-row guards.

```sh
sh docs/network/tests/run-phy-temperature.sh
python3 -m unittest discover -s docs/network/tests -p 'test_audit_phy_temperature.py'
python3 docs/network/tests/audit_phy_temperature.py \
  --elf "$ELF" --map "$MAP" --label temperature-source \
  --expect-temperature source
```

The allocation checker has 19 passing synthetic regressions. Its full tracking
profile requires the previous source printf, wrappers and dispatcher gates,
no allocated `libpp.a`, retained helpers/state, the aligned 30-byte table,
all five correct source aliases and no selected vendor text/literal input.
`--expect-temperature vendor` instead requires all five original bodies and
no defined source replacement symbols. Reports contain hashes and addresses,
separating original alias sizes from actual source-body sizes.

Lifetime-only firmware can legitimately discard unused PLL/RF tracking helpers
and consequently fail that strict profile. Its selected aliases and input
ownership are inspected separately; the complete gate applies to images that
exercise the tracking path. A lifetime-only omission is not evidence that the
tracking helpers were replaced.

Native v4 keeps the generic inner and range implementations out of line to
avoid duplicating their bodies in each exported wrapper. In the v4 builds,
unique source function text totals 476 bytes on C3 and 385 on S3, counting
the shared inner/forward export address once. Named source lookup tables add
55 bytes per chip; S3's named literal inputs add 28 bytes. Those named inputs
sum to 531 and 468 bytes respectively, excluding shared panic support and
linker padding. These are scoped code/data measurements, not a whole-firmware
size reduction; vendor alias `ST_SIZE` values must not enter those sums.

## Remaining PHY work

Both chips retain `phy_set_tsens_power`, `phy_xpd_tsens`, `get_temp_init`,
the initialization/restore/shutdown paths, `phy_param`, `g_phyFuns` and
`phy_tsens_attribute`. C3 additionally retains `rom2_tsens_read_init1` and
`rom2_temp_to_power1`, and obtains sensor code through ROM. S3 retains
`tsens_read_init_new`, `ram_tsens_code_read` and `ram_temp_to_power`.
I2C access and code-to-temperature conversion still call initialized PHY-table
entries backed by ROM; S3's sensor-code slot is patched to its retained RAM
helper. Static ROM-reference symbols do not establish live callback addresses.

The replacement therefore removes five allocated function bodies without
removing `phy_tsens.o`. The current full images still allocate 18 `libphy.a`
members. RF initialization, channel/PLL setup, RX/TX calibration, gain/power
tracking and register/I2C/PBUS support also remain. The next boundaries should
follow these dependencies, with the existing tracking cadence and calibration
policy held fixed during the [device comparison](PHY-TEMPERATURE-VALIDATION.md).
