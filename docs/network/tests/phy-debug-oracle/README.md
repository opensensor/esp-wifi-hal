# PHY debug original-instruction oracle

`original-instructions.json` pins the selected `get_iq_value`,
`get_bias_ref_code` and `phy_get_vdd33` bodies from the preceding feature
milestone's C3/S3 source station ELFs. `baselines.json` records ELF/map hashes.
`extract.py` restarts disassembly at each reachable PC and checks encoded bytes
against the ELF. This avoids the misleading linear decode of padding before
S3 address `0x42041ce0`. Reachable instruction counts in the above order are
C3 24/52/63 and S3 24/44/52.

`verify.py` checks body hashes, instruction bytes/bounds, supported opcodes,
branch reachability and recorded literals before interpreting the instructions.
Checks stay active with Python `-O`. Unknown memory/helper targets and invalid
case domains fail. Execution is bounded by instruction, nesting and callback
budgets. Stack operations are modeled; external callbacks clobber caller-saved
registers while preserving the chip ABI. Only their meaningful argument
registers enter the trace.

Each chip has 374,130 cases: 168,000 IQ, 66,144 bias and 139,986 voltage. IQ
covers every 16-bit packed value under selectors zero/one, all low 12 bits
under eight additional selectors, every byte selector at component boundaries,
and high packed-bit patterns. Bias includes every 16-bit ADC return plus raw
32-bit edges and mutation patterns. Voltage varies all 16-bit samples and all
16-bit bias returns, adds signed/overflow boundaries, and covers every 12-call
table-mutation mask with zero/nonzero bias. These are bounded cases, not an
exhaustive proof over every 32-bit argument combination or analog state.

Cases are sixteen little-endian u32 words:

| Word | Meaning |
| --- | --- |
| 0 | Operation: IQ 0, bias 1, voltage 2 |
| 1–2 | Packed IQ input and raw selector |
| 3–4 | Raw bias and voltage ADC returns |
| 5 | Table-generation mutation mask, one bit per callback, at most 12 bits |
| 6 | Voltage bias call: opaque result 0, execute original/source bias 1 |
| 7 | Advance table generation at the direct bias boundary |
| 8 | Caller-saved poison seed and irrelevant callback return seed |
| 9–15 | Reserved zero |

The output appends the observed return, event count and eight u32 words per
event. IQ returns are normalized to zero because the interface is void.
Events: byte write 1 (destination, offset, low byte), table read 4 (generation),
slot read 5 (offset, generation), callback 6 (target and up to six arguments),
and direct bias call 9. Callback snapshots are synthetic, allowing table
mutation to be observed; they are not recordings of hardware memory.

The Rust harness imports `esp-wifi-hal/src/phy_debug.rs` and mocks only the
external access boundary. It compares the actual production return and full
ordered trace at O0 and O2. `expected-results.json` pins counts and hashes.
Run the complete comparison with `sh docs/network/tests/run-phy-debug.sh`.
Native C ABI, instruction timing, calibration, ROM/ADC behavior and real-device
reliability require separate evidence; this oracle does not establish them.
