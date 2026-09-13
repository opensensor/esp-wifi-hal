# Original-instruction PBUS oracle

This fixture interprets the pinned linked vendor instructions for five C3 and
four S3 PBUS functions. It does not execute, import, or translate the production
Rust implementation. The Rust host boundary test consumes its binary event
stream and compares the production functions at optimization levels 0 and 2.

The baseline is `source-v2-sta_smoke.elf` from the preceding sensor lifecycle
milestone. Its ELF and map hashes are recorded in
[`phy-sensor-lifecycle-validation.json`](../../phy-sensor-lifecycle-validation.json),
under `allocations/esp32c3/source-v2` and `allocations/esp32s3/source-v2`.
The fixture contains only the selected instruction bodies, required literal
words, a ten-entry jump table per chip, and 60 C3 / 80 S3 bytes of constant
programming data. It contains no complete firmware, live PHY state,
calibration values, credentials, or packet captures.

| Operation | C3 original | Bytes | S3 original | Bytes |
|---|---|---:|---|---:|
| 0 | `ram_pbus_force_mode` | 150 | Not selected; rejected | — |
| 1 | `txcal_debuge_mode` | 132 | `txcal_debuge_mode` | 100 |
| 2 | `txcal_work_mode` | 54 | `txcal_work_mode` | 42 |
| 3 | `save_pbus_reg` | 62 | `save_pbus_reg` | 74 |
| 4 | `set_pbus_mem` | 584 | `set_pbus_mem` | 524 |

`extract.py` checks the private ELF hash, verifies each instruction encoding
against the original bytes, and restarts disassembly at reachable PCs. In the
S3 `set_pbus_mem`, the jump table enters `0x4203ac52`. The preceding zero byte
at `0x4203ac51` is padding: a linear disassembly misleadingly combines it with
the next instruction into `mul16u`. The interpreter follows the recorded jump
table and models both Xtensa hardware loops. It rejects unsupported
instructions, unknown targets, uninitialized stack reads, missing literals,
unknown memory/callback boundaries, overlapping instructions, altered hashes,
and nonzero unrecorded code. Rejection uses ordinary checks and remains enabled
under Python `-O`.

## Observable contract

All five APIs are void: their incidental return registers are not contractual
and the stream records return zero. Callback caller-saved registers are
deliberately clobbered in the interpreter; saved arguments must survive by the
original ABI. Actual returns from the index helper remain raw 32-bit values.

* C3 force mode tests the full argument register for zero. A nonzero argument
  clears bit 27 at `0x6000610c`, then sets bit 0 at `0x60006104`. Zero clears
  bit 0 first, sets bit 27 second, then reads bit 1 at `0x6002600c`. Only when
  that bit is set does it delay 1 µs, replace the top byte of `0x6001c02c`
  with `0x32`, reread and set bit 23, delay 2 µs, then reread and clear bit 23.
  The three reads of that final register cannot be cached across writes or
  delays. No S3 force-mode body is inferred from these C3 instructions.
* Debug mode reads an index byte from C3 `phy_param+0xa3` or S3 `+0x20c`.
  Its mode byte is at `+14+index`, and its gain halfword at `+32+2*index`.
  Every byte index 0–255 stays inside both pinned parameter objects. Those
  arrays can overlap the index byte itself, which the synthetic cases retain.
  C3 order is index, gain, table pointer, slot pointer, mode, first callback.
  S3 order is index, mode, gain, table pointer, slot pointer, first callback.
  Both capture mode and gain before callbacks can mutate parameter memory.
* Debug mode performs six calls, reloading `g_phyFuns` and its selected slot
  before each. C3 slots are `0x50, 0x1d4, 0x1ec, 0xec, 0x1f0, 0xfc`;
  S3 slots are `0x44, 0x1b0, 0x1c8, 0xdc, 0x1cc, 0xe8`. Their arguments are
  respectively `1`, none, `(mode, gain)`, `gain`, parameter pointer, none.
  The pointer is `phy_param + 0x124 + (index_helper_result << 3)` with 32-bit
  wrapping arithmetic. C3 uses the full result; S3 explicitly narrows it to
  16 bits before shifting. This boundary passes the pointer to an opaque
  callback without dereferencing it. It does not invent bounds on that
  callback's eventual accesses or claim arbitrary offsets are safe to use.
* Work mode first directly calls retained `stop_tx_tone(1)`, then loads and
  invokes three independently selected callbacks. C3 slots are
  `0x50(0), 0x1e4(0), 0x1d8()`; S3 slots are
  `0x44(0), 0x1c0(0), 0x1b4()`.
* Saving alternates each 32-bit read at `0x600060e0` through `0x600060f4`
  with its parameter store, at C3 offsets `0x328..0x33c` or S3
  `0x2ac..0x2c0`. It does not batch all reads before the stores.
* Memory programming traverses twelve selector stages in the original jump
  table order. It writes 42 C3 / 46 S3 words to `0x600060cc`. Each data write
  is followed by a fresh control read, write, second fresh read, and second
  write at `0x600060c8`. It finally runs the selected save body. The full
  observable trace has 246 C3 / 266 S3 events. S3 has additional `0x1801ff`
  words and a `0x4831ff` patch; the second C3 eight-word row instead patches
  its second word to `0x14fdff`. These distinctions come from the original
  constants, stack writes, copies, and branch table rather than shared Rust
  arrays.

The selected `set_pbus_mem` calls/tail-calls `save_pbus_reg` from the same
archive member. Link replacement must also cover that internal reference.
All table callbacks and direct `stop_tx_tone`, ROM delay, and `memcpy` remain
opaque boundaries here. `memcpy` is modeled only for its bounded constant-to-
stack copies; production may use constant slices instead. Stack accesses,
read-only constant accesses, and `memw` are not observable event records.
Consequently this is evidence for ordered boundary behavior, not a proof of
physical memory-barrier timing, radio timing, retained callback correctness,
or packet-loss elimination. Native disassembly review and device comparisons
are separate checks.

## Fixed binary case format

Each case is 24 little-endian `u32` input words, one expected-return word
(zero), one **event count** word, and that many nine-word event records.
Unused event words are zero. The count is events, not words or bytes.

| Input word | Meaning |
|---:|---|
| 0 | Operation 0–4 from the scope table |
| 1 | Raw force-mode argument |
| 2 | Initial index, narrowed to its low byte |
| 3 | Synthetic parameter-fill seed |
| 4 | Raw index-helper return value |
| 5 | Table-replacement mask: bit `n` increments the table generation after opaque callback `n` |
| 6 | Parameter-mutation mask using the same callback ordinals |
| 7 | Byte XOR applied to every parameter byte for each selected mutation |
| 8 | Dynamic MMIO read XOR seed |
| 9 | XOR applied to `0x6001c02c` after the 1 µs delay |
| 10 | XOR applied to that register after the 2 µs delay |
| 11 | Reserved; must be zero |
| 12–23 | Initial MMIO values in the order below |

Parameter byte `offset` initially equals `((offset * 37) ^ input[3]) & 255`;
the selected index byte is then overwritten with `input[2] & 255`.
The MMIO value order is:

```
600060c8 600060cc 600060e0 600060e4 600060e8 600060ec
600060f0 600060f4 60006104 6000610c 6002600c 6001c02c
```

S3 uses the first eight registers only. Every MMIO read returns the current
register value XOR `input[8].rotate_left(global_read_count % 32)`. The counter
starts at zero and increments for every MMIO read; a write replaces the
current register value. The two delay XORs occur after their delay events and
do not increment the callback ordinal. Direct `stop_tx_tone` does count as
callback zero in work mode, so table replacement there affects the first
subsequent table load. Table/parameter masks contain six bits only. Opaque
mutations do not generate extra explicit read/write events.

| Event ID | Following words, then zero padding to nine words total |
|---:|---|
| 1 | Parameter read: width in bytes, relative offset, raw value |
| 2 | Parameter write: width in bytes, relative offset, raw value |
| 4 | Table load: generation |
| 5 | Slot load: byte offset, generation |
| 6 | Callback: slot offset, generation, up to six actual arguments |
| 7 | MMIO read: absolute address, raw value |
| 8 | MMIO write: absolute address, raw value |
| 9 | Delay: microseconds |
| 10 | Direct stop-tone call: argument (1) |

For event 6's parameter-pointer callback, argument zero is the wrapping
parameter-relative offset instead of the build-dependent absolute pointer.
Zero-arity calls have six zero argument words; incidental argument registers
are not API arguments. Event ID 3 is unused.

## Reproduce and validate

Run the focused behavior and rejection tests without any private inputs:

```sh
python3 -m unittest discover -s docs/network/tests/phy-pbus-oracle -p 'test_*.py'
python3 -O -m unittest discover -s docs/network/tests/phy-pbus-oracle -p 'test_*.py'
```

Generate a corpus into a private or temporary destination:

```sh
python3 docs/network/tests/phy-pbus-oracle/verify.py esp32c3 /tmp/pbus-c3.bin
python3 docs/network/tests/phy-pbus-oracle/verify.py esp32s3 /tmp/pbus-s3.bin
```

`expected-results.json` pins 104,126 C3 and 98,840 S3 cases and their complete
binary SHA-256 digests. Cases cover every parameter-index byte, every helper
return low halfword with nonzero upper bits, additional full-register wrapping
boundaries, all six-bit callback-mutation masks, every force branch, walking
MMIO bits, evolving read values, and all twelve programming stages.

To re-extract a chip from the local private pinned ELF, provide its compiler
toolchain's objdump explicitly:

```sh
python3 docs/network/tests/phy-pbus-oracle/extract.py \
  esp32c3 /private/source-v2-sta_smoke.elf /toolchain/riscv32-esp-elf-objdump \
  /tmp/pbus-c3-extraction.json
```

The per-chip extraction must equal the corresponding `chips` object in
`original-instructions.json`. The published fixture and interpreter are
self-contained for host verification; a private ELF or licensed decompiler
is not needed to run the tests.
