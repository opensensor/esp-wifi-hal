# Basic PHY original-instruction oracle

This oracle executes reachable instructions extracted from pinned C3/S3
linked station ELFs, independently of the Rust implementation. `baselines.json`
records the ELF/map hashes; `original-instructions.json` contains the selected
bodies, literal values and helper targets. `extract.py` can reproduce the
fixture when those private build artifacts and Espressif objdump are available.
They are not needed to run the checked-in host tests.

`verify.py` reuses the earlier instruction executor and supplies a separate
memory/helper boundary model. It rejects unrecognized instructions, helpers,
memory accesses, malformed cases and exhausted polling budgets. Fixture and
case hashes are checked with explicit conditions that remain active under
`python3 -O`.

The production harness imports `esp-wifi-hal/src/phy_basic.rs`, replacing only
the native access adapters. It compares the return value and complete ordered
trace against the oracle at optimization levels zero and two.

| Chip | Reset | Channel-14 | Interpolation | Total |
| --- | ---: | ---: | ---: | ---: |
| C3 | 4,096 | 22,976 | — | 27,072 |
| S3 | 4,096 | 22,976 | 787,712 | 814,784 |

Reset cases cover both hosts, busy/idle combinations, delayed poll completion,
exact reset writes and register mutation at critical entry. Channel cases
cover raw upper argument bits, signed power bytes and unrelated register bits.
Interpolation covers every byte pair for channels 1–11, all low-byte channel
values, upper argument aliases, signed division and output wrapping.

The pinned critical entry/exit no-op helpers share an address. The oracle
records both boundary calls with the same helper kind and uses call ordinal
for entry mutation. It does not invent distinct original targets.

Fifteen focused tests include fixture corruption and unsupported-domain
rejections. Run everything with:

```sh
sh docs/network/tests/run-phy-basic.sh
```

These finite modeled cases establish agreement at the represented boundaries.
They do not model analog behavior, bus cycle timing, concurrent hardware
changes outside the polling model, or the retained power and ROM routines.
