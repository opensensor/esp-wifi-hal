# Original tracking-dispatcher instruction oracle

`run-phy-dispatcher.sh` compares the actual production Rust dispatcher against
this bounded interpreter of the pinned original C3/S3 instruction ranges. It
needs Python 3 and stable Rust; no device, cross compiler or PHY blob is needed
to replay the committed fixtures. Temporary exhaustive case files are removed
after the test. Both optimization levels zero and two are checked.

The input is the exact `combined-sta_smoke` ELF from the prior source-wrapper
milestone, identified in `PHY-POWER-CONTROL.md` and its inventory. Extraction
verified ELF SHA256, the original 122-byte C3 / 78-byte S3 function hashes, code
bytes and three S3 address/mask literals. Only those bounded instructions,
symbol addresses and provenance hashes are included; no firmware, parameter
contents, calibration data or network configuration is published.

The interpreter follows the recorded branches, stack saves/restores, register
operations, byte/word reads, literal loads and direct/indirect calls. C3 volatile
registers and S3 outgoing window registers are clobbered at opaque helper calls.
Only stack stores are allowed in the interpreted dispatcher. Unknown operations,
targets, callback slots, literals, parameter sizes and code mismatches fail.
Five negative tests also run with Python assertions disabled.

All analog calls are opaque boundaries. The host fixture defines adversarial
helper effects: changing the active callback table, later optional flags and
argument bytes. These are testing behaviors, not replacement calibration code.
The Rust test imports the production `dispatch<Access>` implementation and
substitutes only that boundary. It must match the original sequence of reads,
table reloads, slots, helper calls/arguments and the complete enter/exit token.
Native pointer/ABI code is checked separately in crossbuilt disassembly and
device tests; the generic host backend alone cannot establish its correctness.

The 137,216 C3 and 268,288 S3 cases exhaust all 65,536 valid byte argument pairs,
all C3 gate-byte combinations and all S3 upper-halfword gate values (with three
lower-halfword patterns). They also cover every argument byte, optional flag
values 0/1/128/255, opaque token extremes, and all 256 helper-mutation masks.
The fixed `expected-results.json` hashes every input and complete expected trace.
The oracle is derived from original instructions, not the replacement source.

The native S3 compiler emits extra `memw` barriers for volatile reads; instruction
identity or timing identity is not claimed. Device callers currently use `(1,0)`,
which the optimized linked Rust function specializes. Analog behavior, long-term
RF performance and calibration algorithms remain outside this host oracle.
