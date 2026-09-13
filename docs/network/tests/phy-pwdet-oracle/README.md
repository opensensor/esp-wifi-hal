# Power-detector original-instruction oracle

The fixtures contain reachable, byte-checked instructions from the preceding
PHY debug milestone's station ELFs, pinned by `baselines.json`. `extract.py`
requires those original ELFs, pyelftools and the target GNU objdump. The
fixture contains nine C3 and eight S3 functions, parameter/table boundaries
and the ROM delay target. It is not a complete firmware or ROM image.

`verify.py` checks hashes, instruction bytes, bounds, reachable PCs, opcode
allowlists, known literals and callback domains before interpreting the
instructions. It models RISC-V saved registers/stack frames and Xtensa call
windows. Opaque calls poison caller-saved registers. It supports nested tone,
sample, reference and FM calls, plus the C3 setup callback's source PKDET path.

`../phy_pwdet.rs` imports the production Rust module and substitutes only its
memory/callback boundary. The same cases compare the returned value, outcome
and ordered trace at O0 and O2. The native implementation uses a sixteen-byte
aligned sample buffer; the host boundary fills all eight halfwords and checks
alignment. Native disassembly separately checks buffer extent and spill
separation. The retained ROM output bodies are in
`rom-buffer-boundary.json`, with installed ROM ELF/body hashes and no local
paths. Runtime callback addresses were observed during the control probes.

| Chip | Cases | Successful returns | Modeled divide exceptions | Bounded non-completing prefixes |
| --- | ---: | ---: | ---: | ---: |
| C3 | 457,298 | 457,261 | 0 | 37 |
| S3 | 456,238 | 456,212 | 8 | 18 |

Cases cover each 16-bit reference axis, sample value, signed numerator and
offset, boundary combinations, all sixteen output-location layouts, all
32 helper-composition modes, callback table/parameter mutation masks, each
valid byte count, high request bits and finite/stalled polling schedules.
These are separate sweeps and targeted combinations, not an exhaustive
Cartesian product or proof across every possible machine state.

Each case is sixteen little-endian u32 words:

| Word | Meaning |
| --- | --- |
| 0 | Operation: no-op, reference, tone, C3 PKDET, read wrapper, samples, FM, linear, dB (0–8) |
| 1 | Raw input, requested count or dB offset |
| 2–3 | Initial parameter halfwords +0xda/+0xdc |
| 4–5 | Sample seed and per-collection increment; seed is also the opaque sample return |
| 6–7 | Alternating raw conversion returns |
| 8 | Nested tone/sample/reference/FM/C3-setup bits (0–4) |
| 9–10 | Table and parameter mutation masks, indexed modulo 32 callbacks |
| 11 | Signal/reference destinations from external halfword pair or parameter fields |
| 12 | Initial MMIO seed |
| 13 | Eight cyclic readiness nibbles; each read of 0x6000e050 consumes one |
| 14–15 | Opaque reference/FM output halfwords |

The stream adds outcome, return value, event count and eight-u32 event
records. Events identify parameter reads (1), external writes (2), table
reads (4), slots (5), callbacks (6), MMIO reads/writes (7/8), direct helpers
(9), buffer halfword writes (10), and delays (11). Scratch addresses are
normalized at call boundaries; private stack accesses are not external
memory events. Output aliasing retains real relative locations.

Outcome zero is a return, one is S3's native QUOU zero-divisor exception,
and two is an observable-prefix budget. A zero-readiness schedule has a
96-event budget; C3 wide-count cases use 6,000 events and cross the counter
wrap. Budget exhaustion is not reported as completion. A separate instruction
budget rejects interpreter errors. Native code does not acquire these budgets
or host panic handlers.

Run `sh docs/network/tests/run-phy-pwdet.sh` to regenerate the hash-checked
corpus and compare production at both optimization levels. The twenty-one
focused tests also run with Python assertions disabled. Original-instruction
traces do not establish analog accuracy, RF equivalence or cycle timing.
