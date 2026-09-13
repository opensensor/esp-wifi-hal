# C3/S3 PHY API member replacement

`esp-wifi-hal/src/phy_api.rs` supplies the remaining selected `phy_api.o`
entrypoints in Rust. Strong linker assignments route callers to source and
remove the complete allocated member, including the old sensor power body
that previously shared its IRAM section. The existing sensor lifecycle
implementation continues to supply `phy_xpd_tsens`.

| Entry | C3 | S3 | Source placement |
| --- | --- | --- | --- |
| `phy_wakeup_init` | Source | Source | IRAM |
| `phy_close_rf` | Source | Source | IRAM |
| `phy_get_rf_cal_version` | 1232 (`0x4d0`) | 711 (`0x2c7`) | Flash |
| `phy_set_tx_seed` | Not selected | Source | Flash |

These constants describe the pinned vendor inputs. They are not a discovery
mechanism for arbitrary future library versions. The archive itself is
unchanged; absence is checked in each linked image.

## Preserved behavior

Wakeup first calls the retained `ram1_phy_wakeup_init` on C3 or
`ram_phy_wakeup_init` on S3. It then reads the word at `phy_param+0x120`.
If bit five is clear, it calls retained `get_rf_freq_init`, loads the current
callback table, reads the channel byte at `+0x1f2`, loads slot `0xd8` on C3
or `0xcc` on S3, and calls it with that channel. It finally rereads the flag
word and sets bit five, preserving any changes made by the helpers.

C3 close reads the sensor-off byte at `+0x31f`. When zero it calls the existing
source-selected `rom1_tsens_temp_read`, then calls retained
`ram1_phy_close_rf` and writes byte one at `+0x320`. The write follows the
retained close even if that helper modifies the byte. S3 close simply calls
retained `ram_phy_close_rf`.

S3 TX seed reads the 32-bit register at `0x6001c400`, replaces its low seven
bits with the argument's low seven bits, and writes the result. The upper
25 bits and the original ordered volatile read/write are preserved.

Native adapters use volatile parameter/table accesses and C ABI calls.
The S3 compiler inserts memory barriers for volatile operations. Instruction
counts and cycle timing therefore need not match the original ordinary state
loads. Wakeup's conditional call to flash and C3's temperature call already
exist in the original path; IRAM entry placement does not establish that all
transitive paths can execute with flash unavailable.

## Validation

The [original-instruction oracle](tests/phy-api-oracle/README.md) compares the
actual production Rust logic at optimization levels zero and two against
226,594 cases. It checks access widths, callback order and arguments, fresh
state/table reads after helper mutations, shutdown order and seed masking.
Native code review separately checks ABI, call routing, IRAM entries and S3
literal placement. This is modeled boundary behavior, not analog equivalence.

```sh
sh docs/network/tests/run-phy-api.sh
python3 docs/network/tests/test_audit_phy_api.py
python3 -O docs/network/tests/test_audit_phy_api.py
python3 docs/network/tests/audit_phy_api.py \
  --elf /path/source-sta_smoke.elf --map /path/source-sta_smoke.map \
  --label source --expect-api source
```

The allocation audit composes every previous source milestone gate. It
requires no allocated `phy_api.o` input, actual source bodies at the selected
aliases and original ownership for the retained RF helpers. Its explicit API
stage replaces exactly two helpers in the earlier lifecycle audit; the
older stage still requires their original bodies.

The expanded lifetime probe reads flags and entry addresses and calls the
pure version getter inside each existing PHY guard. It checks the C3 close
flag after release. It does not invoke extra RF operations or alter normal
calibration cadence. Live results and packet counts are recorded separately
in the [device comparison](PHY-API-VALIDATION.md). Low-level RF initialization, calibration, frequency
selection, vendor state and ROM helpers remain dependencies.
