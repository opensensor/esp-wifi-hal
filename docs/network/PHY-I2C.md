# C3/S3 analog I2C replacement

`esp-wifi-hal/src/phy_i2c.rs` supplies the four flash setup functions, and
`phy_i2c_iram.rs` supplies the remaining selected IRAM functions. Together they
remove every allocated `phy_i2c.o` input from both compared station images.
The original archive is unchanged. Strong linker assignments redirect external
and same-member references, including callback installation, before section
garbage collection removes the member.

The [first-stage comparison](PHY-I2C-FLASH-VALIDATION.md) records flash-only
replacement and its packet/request losses. The [complete-member comparison](PHY-I2C-VALIDATION.md)
records the following IRAM stage, expanded callback probe and device results.

| Original function | C3 | S3 |
| --- | --- | --- |
| `phy_get_i2c_data`, `bias_reg_set`, `i2c_bbpll_set`, `phy_i2c_init2` | Source flash | Source flash |
| `phy_i2c_enter_critical`, `phy_i2c_exit_critical` | Source IRAM no-ops | Source IRAM no-ops |
| Host ID, register read/write, first initialization | Source `rom1_*` aliases | Source `ram_*` aliases |
| `phy_i2c_bbtop_wakeup` | Source IRAM | Source IRAM |
| `bias_dreg_i2c_set` | Source IRAM | Not selected |
| `ram_set_txcap_reg` | Not selected | Source IRAM |

C3 retains its ROM-bound `rom_set_txcap_reg` at `0x400019f4`. Its unreachable
142-byte vendor TXCAP body was retained only because it shared the original
IRAM section; dropping that section does not change its ROM routing.

## Chip-specific behavior

The C3 setup initializes its parameter bytes with the original byte, halfword
and word stores. S3 uses byte stores and selects values using the revision byte
at `phy_param+0x20d`. The source preserves access widths and ordering.

C3 bias setup selects its branch using argument bit zero. Its enabled path
computes `max((raw_read - 15) as i16, 60)`, then stores the low byte. Its even
branch originally tails to a local `bias_dreg_i2c_set.part.0` symbol; the source
calls the link-visible `bias_dreg_i2c_set(1)`, whose verified nonzero branch
reaches the same two-write behavior without additional register accesses. The
complete stage supplies that public entrypoint in Rust IRAM as well. S3 tests
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

## IRAM transactions and initialization

The host-ID function preserves the original register mask update and maps block
bytes 98, 99, 100, 103 and 107 to host one, all others to zero. Read/write wrappers
ignore the caller's host argument and obtain a host through the callback table.
They preserve the full pause token and restore it through a freshly loaded
callback. The named critical helpers are empty in the originals; source no-ops
preserve that behavior without inventing a lock. The separate ROM pause/resume
callbacks remain called.

Register reads preserve block/mask/host/register arguments and the full returned
word. S3 narrows block/register inputs to bytes but passes the returned host word
unchanged, as its original caller does; the retained ROM read helper narrows
host internally. Installed host IDs remain zero or one. Write commands retain
32-bit wrapping arithmetic and poll busy bit 25 at the derived host register
until it clears, with the original absence of a timeout. Synthetic host values
in the oracle test arithmetic; they are not valid arbitrary hardware addresses.

The first initializer snapshots twenty parameter bytes in the original order,
then passes six ten-byte arrays, length ten and flag zero to the batch callback.
The four constant block/register arrays occupy a checked 40-byte DRAM object and
are copied into stack arrays through a volatile read. Data arrays remain captured
on the stack. Native inspection checks the eight-argument ABI, RAM literal
placement and any compiler-generated memory helper calls. C3 uses ROM `memset`;
S3 needs no memory helper. The source preserves masked control-register updates,
callback reloads and conditional SAR2 initialization.

S3 TXCAP reads all nine input bytes and, if selected, the saved parameter
triplets. It preserves the low-byte rate bands, two callback writes and the
final fresh parameter read/update. The wakeup helper reads two registers and
calls the flash initializer only when both complete return words equal 16.
This conditional IRAM-to-flash edge already exists in the original; it is not a
claim that every transitive path can run while flash is inaccessible.

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
The complete stage requires the whole original member to disappear, all selected
IRAM aliases to resolve to source in internal RAM, and the exact block/register
table to occupy internal DRAM. The live lifetime probe checks all four C3 and
five S3 selected callback slots against their linked entrypoints after each
normal initialization cycle; it does not invoke additional analog operations.

These checks establish modeled boundary behavior and linked ownership. They do
not establish instruction-cycle or analog equivalence, all RF conditions, or a
fix for the packet-loss and latency issues under investigation. Device results
are reported separately with their measured counts and limitations.
