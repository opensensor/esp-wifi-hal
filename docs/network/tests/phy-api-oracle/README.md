# Original-instruction PHY API oracle

This interpreter executes bounded instructions extracted from the preceding
TX-completion milestone's linked station images, which still use the original
`phy_api.o`. `baselines.json` pins their ELF/map hashes. The extraction checks
the ELF hash and each instruction's bytes; `original-instructions.json` stores
only the seven function bodies, required literals and relevant symbol metadata.
Public host tests require neither those private firmware files nor a decompiler.

| Operation | Function | C3 bytes / cases | S3 bytes / cases |
| --- | --- | --- | --- |
| 0 | `phy_wakeup_init` | 72 / 82,432 | 51 / 82,432 |
| 1 | `phy_close_rf` | 48 / 12,288 | 8 / 12,288 |
| 2 | `phy_get_rf_cal_version` | 6 / 1 | 8 / 1 |
| 3 | `phy_set_tx_seed` | Absent | 30 / 37,152 |

There are **94,721 C3 and 131,873 S3 cases**. The production host test imports
`esp-wifi-hal/src/phy_api.rs` and implements only its access boundary. It
compares the return and complete ordered effect trace at O0 and O2. The oracle
has independent control flow, executing the original RISC-V/Xtensa instructions.
Void returns are normalized to zero; the version getter's return is checked.

The case corpus exhausts the channel byte across flag patterns and helper
mutation combinations, each individual flag bit, every C3 off byte, and seed
boundaries including raw upper bits. S3 close uses the same synthetic state
cases but must never access those C3 fields. Callbacks are opaque and clobber
caller-saved registers. Their synthetic mutations test fresh reads; arbitrary
synthetic states are not claimed valid hardware configurations.

`decode` rejects unsupported opcodes, changed bytes/hashes, overlapping or
missing instructions, unknown branch targets and nonzero unrecorded bytes.
Execution rejects unknown helpers, slots, MMIO, parameter accesses and widths.
The twelve focused tests exercise both meaningful branches and evidence
rejection. Checks stay active under Python `-O`. The whole generated case
stream and canonical fixture hashes are pinned in `expected-results.json`.

## Case format

Each record contains sixteen little-endian `u32` input words, expected return,
**event count**, and that many five-word events, padded with zero words.

| Word | Input |
| ---: | --- |
| 0 | Operation above |
| 1 | Raw seed argument |
| 2 | Initial flags word at `+0x120` |
| 3 | Initial channel byte at `+0x1f2` |
| 4, 5 | Initial C3 off/closed bytes at `+0x31f/+0x320` |
| 6 | Initial S3 seed register word |
| 7, 8 | State-mutation and table-replacement masks |
| 9–11 | Flags after wakeup, frequency init, channel callback |
| 12, 13 | Channel after wakeup/frequency init |
| 14, 15 | Off byte after measurement; closed byte after close |

Mask bit positions identify helpers: zero is low-level wakeup, one frequency
init, two channel callback, three C3 measurement, four low-level close.
A selected table mutation increments its generation. Selected state mutations
apply the corresponding input words, narrowing byte fields. Unselected helper
mutations have no effect. Internal stack/literal accesses are not trace events.

| Event | Payload following ID |
| ---: | --- |
| 1, 2 | Parameter read/write: width, offset, value |
| 4 | Callback table load: generation |
| 5 | Slot load: byte offset, generation |
| 6 | Channel call: slot, generation, channel |
| 7, 8 | MMIO read/write: address, value |
| 9 | Retained helper call: helper kind above |

```sh
sh docs/network/tests/run-phy-api.sh
python3 docs/network/tests/phy-api-oracle/extract.py \
  esp32c3 /private/source-v2-sta_smoke.elf /toolchain/riscv32-esp-elf-objdump \
  /tmp/api-c3-extraction.json
```

The extraction must equal that chip's entry in the fixture. Host evidence
establishes ordered modeled boundary behavior. Native ABI, RAM/literal
placement, analog timing, hardware operation and traffic require separate
review and device validation.
