# Register member instruction oracle

`original-instructions.json` holds reachable instruction bytes/text, literal
values and just three dependencies from the private hash-pinned C3/S3 station
ELFs. `baselines.json` pins both ELF/map and the public fixture; no firmware,
network configuration, calibration dump or signing material is included.

`extract.py CHIP ELF OBJDUMP OUTPUT` re-extracts bodies and literals using GNU
objdump and pyelftools. The checked fixture adds the pinned map input ownership
rows and scope. `verify.py CHIP OUTPUT` needs Python's standard library only.
It emits a stream of 32 case words, result, trace-word count, then eight-word
ordered events. `expected-results.json` pins the stream digest and coverage.

Events: 1 parameter/buffer read; 4 callback table load; 5 slot load; 6 raw I2C
callback; 7 MMIO read; 8 MMIO write; 9 child call; 10 ROM delay. Addresses in
PHY parameter memory normalize to 0x200000. Input buffers start at 0x300000 with
0..3-byte alignment. Stack effects are private interpreter state. All external
calls clobber caller-saved registers; unmodeled accesses or calls fail closed.

Case axes: 0 operation, 1..6 machine arguments, 7 initial MMIO seed, 8 varying
MMIO-read values, 9/10 state-change masks after MMIO writes/reads, 11 mutation
seed, 12 callback table-generation mask, 13 callback state-change mask,
14 callback MMIO-change mask, 15 executed child mask, 16 buffer alignment,
17 parameter/buffer seed, 18/19 C3 AGC thresholds, 20/21 FE byte values.
Remaining words must be zero. Mutation masks are synthetic stimuli and are
not claims about undocumented hardware side effects. Barriers and IRAM/cache
residency require separate native inspection; final register values alone
would not establish the ordered contract tested here.
