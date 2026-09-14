# RX-control original-instruction oracle

Fixtures were extracted from the preceding initialization milestone's pinned
ordinary firmware ELFs. `baselines.json` records ELF/map hashes and selected
symbols; `extract.py` checks original bytes and reachable control flow.
`machine.py` executes the pinned RISC-V or Xtensa instructions; `verify.py`
provides synthetic, bounded register and callback behavior. The Rust runner
uses the independent production implementation through its Access interface.

The original C3 fixture includes five bodies (four public entries and the
compiler-split reset tail); S3 has four. Split-tail calls are composed without
inventing a public boundary. Gain-trigger calls compose the actual body and
retain a boundary event. Delay and four ROM callback slots are explicit
boundaries. They may update the counter, registers or writable callback table.
The private callback buffer is checked by consumed bytes, independent of
initialization instruction width and stack location. No live calibration data,
credentials or keys are included.

Run `../run-phy-rx-controls.sh`. The expected case digests pin coverage and
ordered traces. Nine focused tests check corrupt evidence, unsupported paths,
reset narrowing, completion, counter wrap and sticky saturation state.
