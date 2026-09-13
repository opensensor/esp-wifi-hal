# Original sensor lifecycle instruction oracle

The fixture independently interprets the remaining allocated sensor-member
routines and the RAM `phy_xpd_tsens` wrapper from the exact C3/S3
`source-v4-sta_smoke` baseline ELFs. Their ELF/map hashes are pinned in
[the preceding validation report](../../phy-temperature-validation.json).
The previous five measurement functions in those ELFs are already source
implementations; measurement is therefore an opaque, separately tested
boundary here rather than an invented replacement for the remaining ROM code.

| Operation | C3 original | Bytes | S3 original | Bytes |
| --- | --- | ---: | --- | ---: |
| 0, power | `phy_set_tsens_power` | 28 | `phy_set_tsens_power` | 38 |
| 1, read init | `rom2_tsens_read_init1` | 92 | `tsens_read_init_new` | 86 |
| 2, power-down wrapper | `phy_xpd_tsens` | 48 | `phy_xpd_tsens` | 29 |
| 3, sensor code | remains ROM, not interpreted | — | `ram_tsens_code_read` | 48 |
| 4, temperature to power | `rom2_temp_to_power1` | 38 | `ram_temp_to_power` | 56 |
| 5, temperature state init | `get_temp_init` | 92 | `get_temp_init` | 68 |

These are symbol body sizes, including any internal padding, excluding separate
literals and the attribute table. They are not archive-allocation savings.
The public fixture contains only these bounded instructions, necessary address
literals/symbols, the 30-byte attribute table and provenance hashes. It does not
contain firmware, live PHY state, calibration output or network configuration.

`extract.py` verifies the complete ELF hash before extracting selected symbols,
then records their exact bytes and SHA256 hashes. It starts objdump afresh at
each reachable instruction, explores both branch paths, stops at returns and
keeps inter-function literals/padding out of executable evidence. The replay
decoder checks bytes, hashes, overlaps, reachable instructions and missing
nonzero code. Unknown instructions, targets, callbacks, MMIO addresses, memory
widths and unsupported table accesses fail explicitly. `memw` is recognized as
an ordering instruction; events describe the accesses, while emitted barriers
and native ABI are checked separately in target disassembly.

```sh
python3 docs/network/tests/phy-lifecycle-oracle/extract.py \
  esp32c3 "$C3_BASELINE_ELF" "$C3_OBJDUMP" /tmp/c3-lifecycle.json
python3 docs/network/tests/phy-lifecycle-oracle/extract.py \
  esp32s3 "$S3_BASELINE_ELF" "$S3_OBJDUMP" /tmp/s3-lifecycle.json
python3 -m unittest discover -s docs/network/tests/phy-lifecycle-oracle -v
python3 -O -m unittest discover -s docs/network/tests/phy-lifecycle-oracle -q
python3 docs/network/tests/phy-lifecycle-oracle/verify.py esp32c3 /tmp/c3-cases.bin
python3 docs/network/tests/phy-lifecycle-oracle/verify.py esp32s3 /tmp/s3-cases.bin
```

There are **562,184 C3** and **569,768 S3** cases. Per chip, 524,288 cover all
65,536 wrapping signed-halfword differences with mode registers 0, 1, 256 and
`0xffffffff`, then every difference again with four nontrivial raw 32-bit input
bases. The remaining cases exercise byte domains, flag and return narrowing,
MMIO initial values, changing hardware read values, optional DAC writes and
measurement-side parameter changes. `expected-results.json` hashes every input,
return and event. Temporary exhaustive streams are not committed. Twenty-two
focused tests, including eleven rejection tests, also pass with Python
assertions disabled.

## Important original contracts

- **Power:** C3 replaces bit 22 at `0x60040058` with argument bit zero. S3
  replaces bits 22/23 at `0x60008850` with both bits set when the low argument
  byte is nonzero. These are not interchangeable Boolean conversions.
- **C3 init:** a nonzero first register enables the optional DAC write. Only
  that branch indexes the five-row table with the full second register. It
  loads `g_phyFuns`, loads slot `0x1bc`, reads the attribute DAC byte, and calls
  `(105,0,6,3,0,dac)`, in that order. Subsequent RMWs set bit 10 at `0x600c0014`,
  clear bit 10 at `0x600c001c`, set bit 15 at `0x6004005c`, then tail-call
  power(1). If the first register is zero, even an otherwise invalid second
  register is unused and causes no table access.
- **S3 init:** arguments are unused. Set bit 22 at `0x60008034`, then set bits
  31 and 29 at `0x60008904` using two separate reads/writes. Call power(1),
  then reread `0x60008850` and clear bit 24.
- **Power-down wrapper:** read byte `+0x31f` on C3 or `+0x2a2` on S3; call
  power(0) only when it is zero, then always store byte 1 at that offset.
- **S3 code:** independently read, set bit 24, reread, clear bit 24, and
  reread `0x60008850`; return the final read's low byte. A cached initial
  register value is not equivalent.
- **Temperature to power:** both first subtract raw registers and wrap the
  difference to signed 16 bits. C3 nonzero mode divides positive differences
  by 4 and nonpositive differences by 5; zero mode uses 6 and 4 respectively.
  Division truncates toward zero and the low result byte is sign-extended.
  S3 ignores mode, divides positive differences by 5 and nonpositive ones
  by 4. On the nonpositive path only, if the quotient's signed low byte is
  below -12, decrement the quotient. Return its **zero-extended** low byte.
  The low-byte test wraps for larger negative differences; it is not a
  clamp or comparison of the full quotient.
- **Temperature init:** C3 directly calls the already-source outer measurement;
  S3 loads the current table and calls slot `0x258`. Parameter decisions and
  copies follow that call and must observe helper mutations. C3 uses both
  full-width flag registers; S3 ignores the first and narrows the second to
  a byte. Only sensor-code and temperature-to-power operations have meaningful
  return values in this contract; incidental registers from void APIs are
  deliberately ignored.

The retained measurement boundary always updates `phy_param + 0x92` with the
low halfword of its configured result. The state-copy oracle preserves all
original reads and writes, including the C3 signed halfword read whose stored
bits are unchanged. Synthetic helper mutations exercise later fresh reads;
they do not assert that real calibration helpers perform those mutations.

## Binary case format

All words are little-endian `u32`. A case has 22 input words, then the expected
return register (zero for void operations), then event count, followed by that
many nine-word events.

| Input index | Meaning |
| --- | --- |
| 0 | Operation number above |
| 1–3 | Raw argument registers 0–2 |
| 4 | Initial byte at parameter `+0x204` |
| 5 | Initial halfword at `+0x92` |
| 6 | Initial calibration halfword: C3 `+0x20c`, S3 `+0x206` |
| 7 | Initial saved halfword: C3 `+0x210`, S3 `+0x20a` |
| 8 | Initial halfword at `+0x212`; unused by S3 |
| 9 | Initial power-down flag: C3 `+0x31f`, S3 `+0x2a2` |
| 10–13 | Initial MMIO registers in the order below |
| 14 | Dynamic MMIO read XOR seed |
| 15 | Measurement result, whose low halfword is written at `+0x92` |
| 16 | Synthetic helper mutation mask |
| 17–20 | Post-measurement byte flag, calibration, saved and second halfword values |
| 21 | XOR applied to the power register by the DAC-write helper |

C3 MMIO register order is `[0x60040058,0x600c0014,0x600c001c,0x6004005c]`.
S3 order is `[0x60008850,0x60008034,0x60008904]`, with input 13 unused.
Other parameter bytes start at `0xa5`. Each MMIO read returns its current
register value XOR input 14 rotated left by the global MMIO read count modulo
32; the count starts at zero and then increments. Writes replace the current
register value. This ensures repeated reads cannot silently become cached
reads. A zero XOR seed models stable read values.

Mutation mask bits 0, 1, 2 and 3 replace the flag, calibration, saved and
second parameter values after measurement. Bit 4 advances callback-table
generation after measurement; bit 5 advances it after DAC write. Bit 6 XORs
the power register with input 21 after DAC write. The configured measurement
halfword store always happens, independent of the mutation mask. These opaque
helper side effects do not themselves produce access events.

Each event starts with its kind, followed by the fields below and enough zero
words to reach nine words:

| Kind | Fields |
| --- | --- |
| 1, parameter read | width, offset, raw value |
| 2, parameter write | width, offset, raw value |
| 3, attribute read | width, offset, raw value |
| 4, load `g_phyFuns` | generation |
| 5, load callback slot | slot byte offset, generation |
| 6, opaque callback | slot byte offset, generation, six argument words |
| 7, MMIO read | absolute address, raw value |
| 8, MMIO write | absolute address, raw value |
| 9, C3 direct measurement | no fields |

S3 measurement records kind 6 at slot `0x258` with six zero argument fields;
C3 DAC write records kind 6 at `0x1bc` with its six arguments. Direct internal
power calls expand into original MMIO events. Volatile registers are poisoned
after opaque calls; original RISC-V saved registers/stack and Xtensa register
windows preserve values according to the actual instruction sequences.

## Link and ROM limits

The original init routines have same-member references to power, and C3
`get_temp_init` has a same-member direct measurement reference. S3 installs
the RAM code reader as a callback. Link redirection must cover these references,
not just otherwise undefined external calls. The prior temperature milestone
already established why `--wrap` alone is insufficient.

`phy_xpd_tsens` is originally inside a shared allocated IRAM input. Redirecting
its symbol can remove its execution from the active call graph while leaving
its old bytes allocated alongside other retained functions. Do not claim those
bytes removed solely from the alias. Conversely, the `rom_phy_xpd_tsens`
symbols at C3 `0x40001c1c` and S3 `0x400063cc` remain ROM veneers; those are not
the RAM wrapper interpreted here. C3 sensor-code acquisition, conversion,
analog access and the larger RF calibration/initialization path remain ROM or
vendor boundaries. Host matching cannot establish RF equivalence or hardware
temperature-range behavior.
