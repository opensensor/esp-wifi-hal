# Original temperature instruction oracle

This fixture covers the first five-function temperature boundary from
[PHY-TEMPERATURE.md](../../PHY-TEMPERATURE.md). It interprets the pinned vendor
instructions independently of the production Rust. Sensor code acquisition,
conversion and register access remain opaque callbacks; this is not an analog
sensor simulator or RF validation.

| Operation | C3 | S3 |
| --- | --- | --- |
| 0, decode | `tsens_dac_to_index` | `tsens_dac_to_index` |
| 1, range | `tsens_dac_cal1` | `tsens_dac_cal_new` |
| 2, inner read | `tsens_temp_read1` | `ram_tsens_temp_read_new` |
| 3, forwarding read | `phy_get_tsens_value` | `phy_get_tsens_value` |
| 4, stored read | `rom1_tsens_temp_read` | `ram_tsens_temp_read` |

The fixture contains only selected instruction ranges, the 30-byte immutable
attribute table, referenced symbol/literal addresses, and provenance hashes.
It contains no firmware image, live PHY state, calibration output or network
configuration. The ELF, map, archive and selected function hashes match
[the baseline inventory](../../phy-temperature-baseline.json).

`extract.py` uses pyelftools and the matching GNU objdump to regenerate a chip's
fixture from its private baseline ELF. It verifies the ELF and selected symbol
hashes before extraction. It starts decoding at each reachable instruction,
follows both sides of branches, and stops at returns. In particular, the S3
selector's two zero padding bytes at `0x4203be07` are excluded; the reachable
block starts at `0x4203be09`. Linear disassembly across that padding is wrong.
The decoder checks raw bytes, overlap, coverage and reachable targets again
when replaying the committed fixture. Unknown instructions, literals, callback
slots, memory reads and branch targets fail rather than receiving defaults.

```sh
python3 docs/network/tests/phy-temperature-oracle/extract.py \
  esp32c3 "$C3_BASELINE_ELF" "$C3_OBJDUMP" /tmp/c3-temperature.json
python3 docs/network/tests/phy-temperature-oracle/extract.py \
  esp32s3 "$S3_BASELINE_ELF" "$S3_OBJDUMP" /tmp/s3-temperature.json
python3 -m unittest discover -s docs/network/tests/phy-temperature-oracle -v
python3 -O -m unittest discover -s docs/network/tests/phy-temperature-oracle -q
python3 docs/network/tests/phy-temperature-oracle/verify.py \
  esp32c3 /tmp/c3-temperature-cases.bin
python3 docs/network/tests/phy-temperature-oracle/verify.py \
  esp32s3 /tmp/s3-temperature-cases.bin
```

The case streams are temporary generated artifacts, not committed fixtures.
`expected-results.json` pins every input, return and ordered event with SHA256.
The C3 stream contains 366,074 cases; S3 contains 366,099. Each exhausts every
signed 16-bit temperature against all five valid attribute rows, all 256 DAC
bytes for decoding, and all valid low-nibble caller codes with every upper
nibble. Additional cases cover inclusive range and global selector boundaries,
raw 32-bit helper values, ABI narrowing differences, all 64 helper mutation
masks, and every pair of valid replacement indexes. Nineteen focused tests,
including eleven rejection tests, also run with Python assertions disabled.

## Stream and event contract

Every integer is a little-endian `u32`. A case starts with ten input words:

1. Operation number from the table above.
2. First input argument register.
3. Second input argument register.
4. DAC read callback result.
5. Sensor code callback result.
6. Temperature conversion callback result.
7. Initial parameter index byte at `phy_param + 0xaa`.
8. Helper mutation bit mask.
9. Index written by the code helper when bit 4 is set.
10. Index written by the conversion helper when bit 5 is set.

The next words are the expected full return register and event count. Exactly
that many nine-word events follow. Each starts with a kind followed by the
listed fields, padded with zeroes to nine words:

| Kind | Fields |
| --- | --- |
| 1, parameter read | width in bytes, offset, raw value |
| 2, parameter write | width in bytes, offset, raw value |
| 3, attribute table read | width in bytes, offset, raw value |
| 4, load `g_phyFuns` | table generation |
| 5, load callback slot | table byte offset, table generation |
| 6, opaque callback | slot byte offset, generation, six argument words |

Only actual formal callback arguments are recorded; unused argument fields
are zero. Read-DAC has three arguments `(105,0,6)`, read-code has none,
conversion has two `(raw_code,signed_attribute)`, and write-DAC has six
`(105,0,6,3,0,dac)`. Signed arguments use their complete 32-bit register bits;
signed memory reads record raw byte/halfword values before extension.

Mutation bits 0, 1, 2 and 3 replace the callback table after DAC read, code
read, conversion and DAC write respectively. Bits 4 and 5 replace the stored
index after code read and conversion. These are synthetic opaque-helper
effects for checking fresh reads and ordering, not claims about live ROM
behavior. The immutable attribute table is not mutated. Callback return
registers are poisoned after writes, and volatile registers are clobbered
at opaque calls; the selector must still return its selected DAC. RISC-V
stack saves/restores and nested calls execute normally. Xtensa direct calls
use separate window registers and transfer their outgoing/return register
values. The original call boundaries remain explicit in the interpreter.

## Domain and ABI limits

DAC values `5,7,15,11,10` decode to indexes `0..4`. Other values decode to
sentinel 5. There are exactly five six-byte attribute rows. A range/full-read
attempt to access index 5 fails the oracle; the fixture neither supplies a
sixth row nor clamps the index. A sentinel decoder result is tested separately
and is not evidence that a full measurement with that DAC is supported.
The code helper runs after the sentinel has been stored and before the first
attribute read. Synthetic cases also cover that helper restoring a valid
index: these have no out-of-bounds access, and must not be rejected eagerly
at decoding. The supported live hardware/caller domain requires separate evidence.

S3 explicitly narrows decoder input and range index to eight bits and range
temperature to signed 16 bits. C3 compares the incoming registers directly;
its ordinary inner caller masks the DAC to four bits and reloads the index
as a byte. The conversion result is preserved as a complete 32-bit register
through the inner and forwarding routines on both chips. The outer routine
returns it unchanged while storing only its low halfword at `+0x92`.

The index is reread after both code and conversion callbacks. Both chips
reload `g_phyFuns` before loading the signed attribute byte. After DAC decoding,
C3 loads the code callback slot before the index store; S3 stores the index
before loading that slot. The trace retains these differences. Native callback
signatures, linking and hardware behavior still need cross-build/device checks;
an interpreter/host trace match cannot establish those properties.
