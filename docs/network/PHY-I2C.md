# C3/S3 analog I2C replacement

`esp-wifi-hal/src/phy_i2c.rs` replaces the four flash setup functions from
`phy_i2c.o`: `phy_get_i2c_data`, `bias_reg_set`, `i2c_bbpll_set` and
`phy_i2c_init2`. Strong linker assignments redirect external and same-member
calls to the `__opensensor_i2c_*` source exports. The original archive is
unchanged; section garbage collection removes the selected inputs.

This is the first stage of the member replacement. The shared IRAM section,
low-level transactions, batch initialization and wakeup helper still come from
the original member. The retained wakeup helper can call the source flash
`phy_i2c_init2`, preserving its existing IRAM-to-flash call path. Critical-section
policy and ROM dependencies are unchanged.

## Chip-specific behavior

The C3 setup initializes its parameter bytes with the original byte, halfword
and word stores. S3 uses byte stores and selects values using the revision byte
at `phy_param+0x20d`. The source preserves access widths and ordering.

C3 bias setup selects its branch using argument bit zero. Its enabled path
computes `max((raw_read - 15) as i16, 60)`, then stores the low byte. Its even
branch originally tails to a local `bias_dreg_i2c_set.part.0` symbol; the source
calls the link-visible `bias_dreg_i2c_set(1)`, whose verified nonzero branch
reaches that same retained body without additional register accesses. S3 tests
the low byte for nonzero and rereads the revision byte after its first write
callback.

`phy_i2c_init2` preserves 33 callback calls on each chip. C3 caches three
calibration bytes before the callbacks; S3 captures one later and rereads other
fields. S3 register 29 uses an unsigned 16-bit subtraction before applying a
minimum and narrowing to eight bits. Inputs zero through nine therefore produce
246 through 255; changing this to saturating subtraction would change the
original behavior. Host IDs and several register values also differ between
chips.

Every callback reads `g_phyFuns` and its selected slot afresh. State reads and
writes retain their order relative to table and slot reads. C3 table arguments
use full 32-bit registers; S3 arguments narrow to bytes. Both read callbacks
preserve the raw return word until the caller explicitly narrows it.

## Validation

The independent [instruction oracle](tests/phy-i2c-oracle/README.md) executes
pinned original C3/S3 instructions. It compares ordered parameter accesses,
callback selection and arguments, including callbacks that mutate the parameter
block or replace the callback table. The production source is tested at
optimization levels zero and two.

```sh
sh docs/network/tests/run-phy-i2c.sh
python3 docs/network/tests/test_audit_phy_i2c.py
python3 -O docs/network/tests/test_audit_phy_i2c.py
```

The allocation auditor distinguishes original, flash-replaced and complete
member replacement. It retains all prior formatter, wrapper, dispatcher,
temperature, sensor lifecycle, PBUS and no-`libpp.a` gates. The flash stage must
retain the original IRAM functions while removing the selected flash inputs.

These checks establish modeled boundary behavior and linked ownership. They do
not establish instruction-cycle or analog equivalence, all RF conditions, or a
fix for the packet-loss and latency issues under investigation. Device results
are reported separately with their measured counts and limitations.
