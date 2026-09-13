# PHY feature original-instruction oracle

The fixture contains reachable instructions, bytes, literals and helper
addresses from pinned C3/S3 station ELFs. `baselines.json` records the original
ELF/map hashes. `extract.py` reproduces `original-instructions.json` when those
private artifacts, pyelftools and Espressif objdump are available. The checked-in
fixture is sufficient for host tests; no firmware or credentials are needed.

`verify.py` executes these instructions against a separate modeled boundary.
The production harness imports `esp-wifi-hal/src/phy_feature.rs` and replaces
only its native access adapters. It compares the relevant return value and
complete ordered trace at optimization levels zero and two.

| Operation | Cases per chip |
| --- | ---: |
| Digital ROM backup adapter | 5,220 |
| Frequency ROM backup adapter | 5,220 |
| Power adjustment | 133,632 |
| Channel-mode configuration | 63,168 |
| Total | 207,240 |

Cases cover raw upper argument bits, pointer forwarding and ROM results; every
power byte and channel; all computation input bytes; branch combinations;
callback/table mutation masks; and register patterns. Synthetic mutations at
stores and callbacks distinguish cached table snapshots from fresh reads.
They model observable ordering, not claims about concurrent hardware behavior.

Sixteen focused tests cover call ordering, narrowing, disabled-mode rereads,
enabled-mode clamping, register masks and rejection of corrupted or unsupported
evidence. Explicit fixture/stream hash checks and domain guards remain active
under `python3 -O`.

```sh
sh docs/network/tests/run-phy-feature.sh
```

The eight-word event format records parameter reads/writes, table/slot loads,
callback arguments, MMIO and opaque helper calls. It does not dereference
modeled backup pointers or emulate ROM backup, gain adjustment or analog I2C
operations. Agreement is limited to the represented boundaries and finite
cases; cycle timing, analog effects and RF equivalence need separate evidence.
