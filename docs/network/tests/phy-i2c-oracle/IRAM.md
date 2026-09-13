# Original-instruction IRAM I2C oracle

This is the second, separately versioned I2C fixture. It covers the remaining
allocated IRAM helpers in the same private PBUS baseline ELF used by the
[four-flash fixture](README.md). The flash fixture and its 24-word corpus are
unchanged. No dead C3 TXCAP body is invented or counted as selected source.

`iram_extract.py` produces `iram-original-instructions.json`; ELF/map hashes
come from `phy-pbus-validation.json`, `allocations/*/source-v2`. Only bounded
selected bodies, necessary literal words, and boundary symbol addresses are
published. All parameter, input-buffer, callback-result, and MMIO case values
are synthetic. `iram_verify.py` interprets those original instructions,
including actual stack arrays and internal calls to the selected critical
helpers. Production Rust is not imported or translated.

| Operation | C3 original (bytes) | S3 original (bytes) |
|---|---|---|
| 0 | `rom1_get_i2c_hostid` (56) | `ram_get_i2c_hostid` (63) |
| 1 | `rom1_chip_i2c_readReg` (106) | `ram_chip_i2c_readReg` (82) |
| 2 | `rom1_chip_i2c_writeReg` (114) | `ram_chip_i2c_writeReg` (98) |
| 3 | `rom1_phy_i2c_init1` (454) | `ram_phy_i2c_init1` (446) |
| 4 | `phy_i2c_bbtop_wakeup` (86) | `phy_i2c_bbtop_wakeup` (54) |
| 5 | `bias_dreg_i2c_set` (64) | Rejected |
| 6 | `bias_dreg_i2c_set.part.0` (60) | Rejected |
| 7 | Rejected | `ram_set_txcap_reg` (187) |
| 8 | `phy_i2c_enter_critical` (2) | Same name (5) |
| 9 | `phy_i2c_exit_critical` (2) | Same name (5) |

There are nine selected C3 and eight selected S3 bodies. Only host-ID and
read-register functions have a meaningful return in this contract; other
returns are normalized to zero. The original read-register return is a full
32-bit register value on both chips. Unknown instructions, targets, widths,
memory, slots, array shapes, missing literals, uninitialized stack reads,
overlap, and altered code hashes fail closed. Checks remain enabled under
Python `-O`.

## Original behavior and boundaries

Both host-ID helpers compute `index = low8(block - 98)`, then return 1 only
for index bits selected by `0x227` in the range 0–9. Thus block bytes
98, 99, 100, 103, and 107 map to host 1; all others map to 0. Both still
perform `read(0x6000e048)`, followed by a write of
`(read_value & 0xfffe000f) | 0x1fe00`, regardless of the returned host.

Read-register wrappers ignore the caller's host argument. They pause through
a table callback, preserve its full return token, enter the named critical
helper, obtain a mask and host through separate fresh table callbacks, then
invoke the original read helper with `(block, mask, returned_host, register)`.
After exiting the named critical helper, they reload the table again and
resume with the saved token. The full original read result survives both
exit and resume. C3 passes raw block/register argument registers; S3
explicitly narrows those two arguments to bytes. The S3 call site does not
narrow the host callback result again before passing it onward.

Write-register wrappers also ignore the supplied host. They preserve the
pause token, enter the named critical helper, and obtain a host result.
Their MMIO address is the 32-bit wrapping expression
`(0x18003800 + returned_host) << 2`. C3 constructs the command from raw
arguments as `block | (register << 8) | (data << 16) | 0x05000000`; S3 first
narrows block/register/data to bytes. After the write, both repeatedly read
the same MMIO address until bit 25 clears, then exit the named critical
helper and resume with the saved token. The original has no polling timeout.
The interpreter rejects a stuck-busy test through its instruction budget;
it does not turn that unsupported execution into a successful timeout return.

The named critical helpers contain only `ret` on C3 and `entry; retw.n` on
S3. They themselves perform no lock, interrupt-mask, MMIO, or callback
operation. Events 9/10 mark crossing those named boundaries; they do not
imply actual exclusion or increment the opaque callback ordinal.

For init1, the twenty parameter bytes at `+0xbd..+0xd0` are copied into two
ten-byte data arrays before any opaque callback. C3 reads them in increasing
order. S3's actual read order is:

```
c0 bd c1 c2 be bf c3 c4 c7 c8 c9 c6 ca c5 cb cc cf d0 ce cd
```

The batch callback receives six ten-byte arrays in this order:

| Array | Values |
|---|---|
| 0: first blocks | `107` repeated ten times |
| 1: first registers | `1,2,3,4,5,6,7,8,10,11` |
| 2: first data | Captured parameter bytes `+0xbd..+0xc6` |
| 3: second blocks | `98,98,98,98,98,98,99,100,100,103` |
| 4: second registers | `3,8,10,9,4,0,1,8,4,2` |
| 5: second data | Captured parameter bytes `+0xc7..+0xd0` |

The seventh argument is length 10 and the eighth is flag 0. C3 passes all
eight in `a0..a7`; S3 passes six pointers in `a10..a15` and places length/flag
at the outgoing stack offsets 0/4. The oracle models the original stack
arrays and the two bounded S3 `memset` calls, then records array contents,
not build-specific stack pointers. A production implementation may use
stack or DRAM constants while preserving those contents and boundary order.

Init1 asks the mask callback for block 107 and replaces bits 4–16 of
`0x6000e048` from the callback's raw result. C3 reads the register, loads the
bulk table/slot, then writes the register and calls the bulk helper. S3
performs the read/write before the bulk table/slot loads. After the bulk
call, both reread the register and restore its masked field to `0x1fe00`.
C3 writes that restoration before loading the next table/slot; S3 loads the
table before the write and its slot afterward. A subsequent masked read
`(105,0,4,3,0)` controls SAR2 initialization: only full return zero triggers
argument 1400. C3 calls retained ROM directly; S3 reloads the table and slot
`0x23c`. Both then cross the critical-exit boundary.

Wakeup reads block 103 registers 4 and 6 through two independently loaded
table callbacks (host 1 on C3, host 0 on S3). Only two full-register results
equal to 16 call the separately tested flash `phy_i2c_init2` boundary. A raw
result such as `0x10010` does not qualify. C3 digital bias tests its full
argument for nonzero: nonzero enters the local part body and writes
`(106,0,0,204)` then `(106,0,1,124)`; zero writes 119 to both registers.

S3 TXCAP takes a nine-byte input buffer and a rate narrowed to its low byte.
Rates 0–3 choose the first input row, 4–8 the second, and 9–255 the third.
For each of three components it reads all three input bytes even if an
override flag at parameter `+0x2cd` is set. A nonzero flag replaces that
component's three choices with a triplet from `+0x2ce..+0x2d6`. The flag is
captured before the loop. The first selected byte is passed in full to the
masked write `(107,0,1,3,0,selected0)`. The second write is
`(107,0,2,low8((selected2 << 4) | selected1))`. After both callbacks, TXCAP
rereads current parameter `+0xbd` and stores `(current & 0xf0) | selected0`
without first masking selected0 to four bits, then stores the packed byte
at `+0xbe`. The original's padding at `0x4037b5ab` is excluded; the reachable
block starts at `0x4037b5ac`, not at the misleading linear `lsx` decode.

Callbacks remain opaque, including their actual underlying bus operation,
pause/resume mechanism, original register read, batch operation, and ROM
calibration. Same-member references to critical helpers, the local bias
part, and wakeup's flash initializer require correct link redirection when
production aliases are installed. Matching this corpus does not alone
prove that those native aliases were linked or that all retained ROM code
was replaced.

The Rust host adapter checks the two dynamic batch arrays and reconstructs
the four fixed block/register arrays in its boundary model. Their production
storage is checked separately: `audit_phy_i2c.py` requires the actual linked
`__opensensor_i2c_program` object to contain exactly 40 bytes in internal DRAM
with SHA-256 `80bff8b7d758d09011f9945d97a5b89c7cd28e064b1afd79ee46cf74b50c3df0`.
That value was independently checked against arrays 0, 1, 3, and 4 emitted
by interpreting original init1 instructions on both chips. Likewise, host
operations 8/9 exercise boundary markers; separate native symbol and
disassembly checks establish the linked critical-helper exports and their
no-op bodies. Host traces alone do not establish either native property.

## Case format

Each case is 32 little-endian `u32` inputs, one expected-return word, one
**event count** word, and that many nine-word events. The first-stage
24-word stream must not be parsed with this format.

| Word | Meaning |
|---:|---|
| 0 | Operation from the scope table |
| 1–4 | Raw arguments 0–3: block/host/register/data as applicable |
| 5 | Synthetic parameter seed: byte at offset equals `((offset*37)^seed)&255` |
| 6 | Pause callback token result |
| 7 | Mask callback result (read wrapper and init1) |
| 8 | Host callback result |
| 9 | Original read-register callback result |
| 10 | Init1 masked-register read result |
| 11–12 | Wakeup's two register-read results |
| 13–14 | Low/high words of the table-replacement mask |
| 15–16 | Low/high words of the parameter-mutation mask |
| 17 | Parameter mutation byte XOR |
| 18 | Initial MMIO `0x6000e048` |
| 19 | Evolving MMIO read XOR seed |
| 20 | Callback mutation XOR for `0x6000e048` |
| 21–22 | Low/high words of the MMIO-mutation mask |
| 23 | Number of busy MMIO reads before the first clear read |
| 24 | Initial TXCAP override flag at `+0x2cd` |
| 25–27 | Packed little-endian fallback data: the first nine bytes populate `+0x2ce..+0x2d6` |
| 28–30 | Packed input buffer, first nine bytes |
| 31 | Reserved; must be zero |

The flag, fallback bytes, and input buffer are initialized for every
operation. TXCAP's input pointer is an implicit synthetic buffer; input 2
is its raw rate. For each 64-bit mutation mask, bit `n` applies after opaque
callback `n`, starting at zero. Table mutation increments a generation;
parameter mutation XORs every parameter byte; MMIO mutation XORs only
`0x6000e048`. Critical markers and internal `memset` do not count as opaque
callbacks. A bulk callback counts once, after all six snapshot records.

Every MMIO read returns the current value XOR
`input[19].rotate_left(global_mmio_read_count % 32)`, then increments that
read count. Callback reads use separate supplied results and do not advance
it. For the write-register operation, bit 25 of the polled value is forcibly
set for the first input-23 reads and clear afterward. Writes replace the
current value. The interpreter admits only `0x6000e048` and, for a write
case, that case's explicitly derived wrapped host address as MMIO.

Synthetic arbitrary host results check the original register arithmetic
and caller boundary. They do **not** authorize using those addresses on a
device or assert a valid native host ABI for them. The selected original
host-ID helper returns only 0 or 1; native callback signatures and actual
hardware tests must respect their observed domain. Similarly, instruction
event order does not measure physical I2C timing or establish packet-loss
elimination.

| Event | Payload after the ID, then zero padding to nine words total |
|---:|---|
| 1 | Parameter read: width in bytes, offset, value |
| 2 | Parameter write: width in bytes, offset, value |
| 3 | Input-buffer read: width (1), index, value |
| 4 | Table load: generation |
| 5 | Slot load: slot byte offset, generation |
| 6 | Ordinary callback: slot byte offset, generation, up to six actual arguments |
| 7 | MMIO read: absolute address, value |
| 8 | MMIO write: absolute address, value |
| 9 | Named critical-entry boundary: no payload |
| 10 | Named critical-exit boundary: no payload |
| 11 | Bulk callback header: slot offset, generation, length (10), flag (0) |
| 12 | One bulk array: array index 0–5, three packed little-endian words; last word's upper 16 bits are zero |
| 13 | C3 direct SAR2 boundary: argument (1400) |
| 14 | Direct flash init2 boundary: no payload |

Each bulk header is followed by exactly six array records, in pointer-argument
order. Unused ordinary callback argument words are zero and do not represent
incidental register values.

## Reproduction

```sh
python3 -m unittest discover -s docs/network/tests/phy-i2c-oracle -p 'test_iram*.py'
python3 -O -m unittest discover -s docs/network/tests/phy-i2c-oracle -p 'test_iram*.py'
python3 docs/network/tests/phy-i2c-oracle/iram_verify.py esp32c3 /tmp/i2c-c3-iram.bin
python3 docs/network/tests/phy-i2c-oracle/iram_verify.py esp32s3 /tmp/i2c-s3-iram.bin
```

`iram-expected-results.json` pins 104,768 C3 and 136,000 S3 cases and their
whole-stream SHA-256 digests. Cases cover all host-ID low-halfword inputs
with nonzero upper bits, all block/register/data byte values with raw upper
patterns, host-result wrapping, busy-read counts, callback changes, every
TXCAP rate and selected-data byte boundaries, bulk snapshots, and conditional
SAR2/wakeup branches. Thirty focused tests additionally check behavior,
instruction provenance, unsupported evidence, and stuck-busy rejection.

`iram_extract.py` takes the same positional arguments as `extract.py` and
uses the same pinned baseline. Its per-chip output must equal that chip's
object in `iram-original-instructions.json`. No private firmware is needed
to regenerate the public event corpora from these fixtures.
