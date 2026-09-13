# C3/S3 PHY debug member replacement

`esp-wifi-hal/src/phy_debug.rs` supplies `get_iq_value`, `get_bias_ref_code`
and `phy_get_vdd33`. Strong aliases remove the complete allocated
`phy_debug.o` member in the tested linked profiles. Original vendor archives,
ROM routines, ADC/analog callbacks and calibration policy remain dependencies.

## IQ conversion

The destination receives two byte stores, at offsets zero then one. The first
component is signed five-bit data from packed bits 6–10 when the selector is
zero, or signed six-bit data from bits 6–11 otherwise. The second component is
always signed six-bit data from bits 0–5. C3 tests the full selector register;
S3 narrows it to a byte first. Selector 256 therefore selects different first
component widths on the two chips. S3 also narrows the packed input to 16 bits;
upper bits do not affect either chip's stored components.

## Bias and voltage sampling

Every analog callback reloads `g_phyFuns` and the selected slot. Bias sampling
writes `(106,0,2,1,1,1)` and `(106,0,7,3,2,1)` through the masked-write callback,
then samples ADC selector 3. It preserves the raw result across cleanup writes
`(106,0,2,1,1,0)` and `(106,0,7,3,2,0)`. Cleanup clears those fields; it does not
save and restore their previous values.

Voltage sampling first calls the source bias helper, then performs the
following callbacks. The table is reloaded before every call, including exit.

| Operation | C3 slot | S3 slot | Arguments |
| --- | --- | --- | --- |
| Setup entry | `0x1d4` | `0x1b0` | None |
| Setup mode | `0x1cc` | `0x1a8` | `(4,1,2)` |
| Set analog field | `0x1bc` | `0x198` | `(107,0,9,7,7,1)` |
| ADC sample | `0x150` | `0x12c` | `(3)` |
| Clear analog field | `0x1bc` | `0x198` | `(107,0,9,7,7,0)` |
| Reset mode | `0x1cc` | `0x1a8` | `(4,1,0)` |
| Setup exit | `0x1d8` | `0x1b4` | None |

Between the sample and cleanup, a nonzero bias selects multiplication by 3840
modulo 2^32, signed division by the bias and low-16-bit result narrowing. A
zero bias bypasses both division and narrowing, preserving the raw ADC result.
The result survives all cleanup callbacks. Source division uses wrapping
semantics to avoid a Rust panic for signed MIN/-1. The original C3 DIV and S3
QUOS behavior is described in the [RISC-V M-extension specification, section
13.2](https://docs.riscv.org/reference/isa/v20240411/_attachments/riscv-unprivileged.pdf)
and [Cadence Xtensa ISA summary, QUOS](https://www.cadence.com/content/dam/cadence-www/global/en_US/documents/tools/silicon-solutions/compute-ip/isa-summary.pdf#page=557).

## Validation boundaries

The [instruction oracle](tests/phy-debug-oracle/README.md) compares production
logic with 748,260 cases at both O0 and O2. It executes the original nested
bias call as well as an opaque bias boundary, checks callback arguments and
mutations, preserves raw results and verifies ordered byte writes. Sixteen
focused oracle tests and 159 allocation regressions pass normally and with
Python assertions disabled. The debug allocation audit composes the complete
feature stage and requires all debug inputs to be absent, including literals
and excluded mergeable strings. Earlier stage ownership checks are unchanged.

```sh
sh docs/network/tests/run-phy-debug.sh
python3 docs/network/tests/test_audit_phy_debug.py
python3 -O docs/network/tests/test_audit_phy_debug.py
python3 docs/network/tests/audit_phy_debug.py \
  --elf /path/source-sta_smoke.elf --map /path/source-sta_smoke.map \
  --label source --expect-debug source
```

Native review separately checks all three C ABI entries, callback argument
registers, reloads, source bias routing and result preservation. All entries
remain in flash. Instruction counts, stack usage and volatile barriers differ
from the original; this does not establish cycle or analog equivalence.

The lifetime probe runs ten pure IQ vectors with destination guard bytes per
cycle and records selected functions and five callback slots. It issues no
additional bias/voltage sampling or analog writes. Normal PHY initialization,
teardown and traffic remain the device comparison workload; unusual ADC/RF
conditions are not established by host coverage or address observations.
Device results are recorded in the [comparison report](PHY-DEBUG-VALIDATION.md).
