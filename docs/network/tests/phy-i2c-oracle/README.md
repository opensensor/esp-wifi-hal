# Original-instruction flash I2C oracle

This stage interprets four flash-resident original I2C helpers from each chip.
It does not execute, import, or translate production Rust. Its binary corpus
is consumed by the production host boundary test at optimization levels 0
and 2. Remaining IRAM helpers, critical sections, hardware busy polling, and
the underlying I2C transport are outside this four-function stage.

The baseline is the preceding PBUS milestone's `source-v2-sta_smoke.elf`.
Its ELF/map hashes are pinned in
[`phy-pbus-validation.json`](../../phy-pbus-validation.json), under
`allocations/esp32c3/source-v2` and `allocations/esp32s3/source-v2`.
`original-instructions.json` contains only these bounded instruction bodies,
their required literal words, and the relevant symbol addresses/sizes.
It contains no complete firmware, live calibration state, credentials, or
network captures. Parameter contents and helper return values in test cases
are synthetic.

| Operation | Original function | C3 bytes | S3 bytes |
|---|---|---:|---:|
| 0 | `phy_get_i2c_data` | 78 | 129 |
| 1 | `bias_reg_set` | 152 | 100 |
| 2 | `i2c_bbpll_set` | 252 | 158 |
| 3 | `phy_i2c_init2` | 850 | 628 |

`extract.py` verifies the baseline ELF hash and every extracted instruction's
encoded bytes. It restarts disassembly at reachable PCs, including S3's
disabled bias branch at `0x4203f022`, after padding at `0x4203f021`.
The interpreter rejects unknown instructions/targets, unexpected memory
accesses or widths, unknown callback slots, missing literals, uninitialized
stack reads, overlapping instructions, and altered code hashes. It permits
only zero-valued unrecorded padding. Explicit checks remain active under
Python `-O`. It clobbers caller-saved registers after opaque callbacks so
captured values survive only according to the original ABI.

## Observed contract

All four functions have void semantics; incidental return registers are
normalized to zero. The I2C read helper's returned register is preserved as
a raw 32-bit test value. Parameter byte stores apply their original narrowing.
Callbacks are opaque: this stage tests their ordering, selected table handle,
arguments, and modeled effects without claiming that arbitrary synthetic
helper returns represent hardware calibration values.

* C3 `phy_get_i2c_data` performs seven stores: byte `+0xbd`, halfword `+0xbe`,
  four words at `+0xc0/+0xc4/+0xc8/+0xcc`, and byte `+0xd0`. The halfword is
  `0x0877`; the four words are `0x5f080aa4`, `0x7f05740a`, `0x3f02f000`,
  and `0x410ff3a8`. S3 instead performs twenty byte stores in its observed
  nonsequential order and reads revision byte `+0x20d` after its first two
  stores. Revision 1 chooses bytes `+0xbf=7`, `+0xc0=148`; all other revisions
  choose 8 and 164. S3 also writes `+0xce=148`, `+0xcf=68`, unlike C3's final
  word. Matching final memory alone would miss the store-width and order
  differences.
* C3 `bias_reg_set` branches on argument bit 0. Even arguments tail-call the
  retained local `bias_dreg_i2c_set.part.0`; odd arguments first directly call
  retained `bias_dreg_i2c_set(0)`. Only after that call does the odd path read
  cache byte `+0x9f`. If zero, it calls `readReg(97,0,4)`, computes
  `max(signed16(raw_return - 15),60)`, and stores the result's low byte at
  `+0x9f`. It reloads the table, rereads that byte, loads the write slot,
  stores a copy at `+0xa0`, writes register 6, then calls the mask helper
  with `(97,0,5,6,6,1)` through another fresh table/slot load.
* The local C3 `part.0` symbol is an opaque boundary, not a public native
  symbol requirement. The pinned exported `bias_dreg_i2c_set` starts with
  a full-register zero check and jumps directly to that same local body for
  nonzero arguments. A native adapter may reach the original local body via
  `bias_dreg_i2c_set(1)` while retaining the distinct boundary event below.
  This does not replace either retained IRAM body in the four-helper stage.
* S3 bias tests whether the argument's low byte is nonzero. Disabled mode
  writes `(106,0,0,119)` and `(106,0,1,119)`. Enabled mode first writes
  `(106,0,0,252)`, then reloads the table and write slot, and only then reads
  revision `+0x20d`: revision 1 chooses the second value 127, otherwise 124.
  A helper mutation between calls therefore changes the second value.
* PLL setup begins with three common masked writes to block 102. C3 has a
  fourth masked write to register 4. The subsequent original read order is
  C3 registers `9,10,4,5` and S3 registers `9,10,5`. Both store low bytes to
  `+0xd1/+0xd2`; C3 additionally stores `+0x31d/+0x31e`, while S3 stores
  `+0x2a1`. After the first read, C3 reloads the table, stores `+0xd1`, then
  loads the next slot; S3 reloads both table and slot before that store.
  C3 reads gate byte `+0x323` before storing `+0x31d`; S3 stores `+0xd2`
  before reading gate `+0x2a6`. A zero gate causes an extra masked write
  `(102,0,5,7,7,0)`. The final register-5 read always occurs.
* Both init helpers perform 33 callbacks with a fresh table/slot load for
  every call. C3 begins by reading `+0x16d`, `+0x16e`, and `+0x16c`, caching
  `min(first+10,60)`, `min(second+3,60)`, and the third byte. Registers 29 and
  31 receive the two cached derived values; registers 22 and 23 receive the
  cached third byte plus 4, narrowed to a byte. Most other parameter bytes
  are reread before their corresponding calls.
* S3 captures `+0x16d` immediately before callback 13, after twelve fixed
  writes. It computes `max(unsigned16(captured - 10),5)` and passes its low
  byte to register 29. Thus captured inputs 0–9 yield 246–255, not 5: the
  subtraction wraps to a halfword before the unsigned maximum. Register 28
  uses a later fresh read. S3 also freshly reads `+0x16c` for both registers
  22/23 and `+0x16e` for both 30/31, without C3's additions.
* Init's block-103 host is 1 on C3 and 0 on S3. Register 55 receives 85 on
  C3 and zero on S3. At the end both write block 98 through host 1, but its
  register 11 receives 104 on C3 and 72 on S3.

The callback slot offsets are C3 `0x1ac/0x1b4/0x1bc` and S3
`0x188/0x190/0x198` for read-register, write-register, and write-mask
respectively. They take 3, 4, and 6 actual arguments. Read callbacks return
the supplied test value; other callbacks deliberately return a poison value
that callers must not accidentally use as saved state.

This is evidence of ordered boundary behavior. It does not establish analog
timing, register-bus transport correctness, retained ROM/IRAM correctness,
interrupt exclusion, or packet-loss elimination. Those require their own
instruction and device evidence.

## Binary cases and events

Each case contains 24 little-endian `u32` inputs, expected return zero, an
**event count**, then that many nine-word event records. Unused event words
are zero. The count measures events, not words or bytes.

| Word | Input |
|---:|---|
| 0 | Operation 0–3 from the scope table |
| 1 | Raw bias argument |
| 2 | Parameter-fill seed: initial byte at offset is `((offset*37)^seed)&255` |
| 3 | Initial cache byte at `+0x9f` |
| 4 | Initial revision byte at `+0x20d` |
| 5 | Initial gate byte at C3 `+0x323` / S3 `+0x2a6` |
| 6–13 | Initial bytes at `+0x167..+0x16e` in increasing offset order |
| 14–17 | Raw read-register callback returns, in read-call order |
| 18–19 | Low/high words of a 64-bit table-replacement mask |
| 20–21 | Low/high words of a 64-bit parameter-mutation mask |
| 22 | Byte XOR used for parameter mutation |
| 23 | Reserved; must be zero |

Byte initializers are narrowed after the synthetic fill. Bit `n` of each
mask applies after opaque callback `n`, starting at zero and counting read,
write, masked-write, and direct-bias callbacks together. A table mutation
increments the table generation; parameter mutation XORs every parameter
byte with input 22's low byte. Opaque effects do not emit separate explicit
memory events. Read-return selection uses its own zero-based read-call
counter. The model rejects more than 64 callbacks or four read callbacks.

| Event ID | Following words, padded to nine words total |
|---:|---|
| 1 | Parameter read: width in bytes, relative offset, value |
| 2 | Parameter write: width in bytes, relative offset, value |
| 4 | Table load: generation |
| 5 | Slot load: byte offset, generation |
| 6 | Callback: slot offset, generation, up to six actual arguments |
| 9 | Direct `bias_dreg_i2c_set`: argument (0 in this stage) |
| 10 | Direct `bias_dreg_i2c_set.part.0`: all remaining words zero |

Event IDs 3, 7, and 8 are unused. Zero-arity direct calls do not expose
incidental argument registers. Stack/literal accesses are internal and do
not generate observable records.

## Reproduction

```sh
python3 -m unittest discover -s docs/network/tests/phy-i2c-oracle -p 'test_*.py'
python3 -O -m unittest discover -s docs/network/tests/phy-i2c-oracle -p 'test_*.py'
python3 docs/network/tests/phy-i2c-oracle/verify.py esp32c3 /tmp/i2c-c3.bin
python3 docs/network/tests/phy-i2c-oracle/verify.py esp32s3 /tmp/i2c-s3.bin
```

`expected-results.json` pins 167,348 C3 and 101,812 S3 cases and their whole
binary SHA-256 digests. The corpus exhausts each byte cache/revision/gate,
the pair of derived initialization inputs, each callback mutation position
through all 33 calls, C3's raw signed-halfword bias computation, and raw
read-return upper-bit patterns. The focused tests check widths/order,
narrowing, callback effects, chip-specific constants, and unsupported
evidence rejection.

To reproduce a per-chip extraction using the private pinned ELF:

```sh
python3 docs/network/tests/phy-i2c-oracle/extract.py \
  esp32c3 /private/source-v2-sta_smoke.elf /toolchain/riscv32-esp-elf-objdump \
  /tmp/i2c-c3-extraction.json
```

The result must equal that chip's object in `original-instructions.json`.
The fixture and interpreter are self-contained for public host validation;
neither the private ELF nor a decompiler is required to run the tests.
