# Hardware-frequency instruction oracle

`original-instructions.json` records the 11 allocated `phy_hw_freq.o` bodies
per chip from the pinned pre-replacement station ELF and map. `baselines.json`
identifies the implementation revision and hashes. Firmware, calibration state
and network configuration remain private.

`extract.py CHIP ELF MAP OBJDUMP OUTPUT` independently re-reads code, literals,
helper symbols and the two jump tables from those hash-pinned inputs. Every
instruction is decoded at a reachable PC and checked against ELF bytes. The
four chip-specific dispatch sites are explicit; all table destinations must
remain inside their owner function. Both fixtures reproduce exactly.

Run the complete host check from the repository root:

```sh
sh docs/network/tests/run-phy-hw-freq.sh
```

The runner checks malformed evidence and focused contracts normally and with
Python assertions disabled. It then executes the original instructions and
compares their ordered traces against the production Rust through a host access
backend at O0 and O2. Reviewed case-stream hashes are checked before success.
There are 1,418 C3 and 1,442 S3 cases, with complete recorded instruction,
conditional-edge and jump-table-destination coverage.

The instruction engine models register and stack argument transport, including
nine-argument entry/call boundaries, nested frames, volatile MMIO, parameter
widths, output buffers, table generations, callback argument/return words and
mutable opaque boundaries. Temporary local storage is compared through passed
pointers, read/write traces while those buffers are callee-visible, and input
snapshots. Private stack-frame layout and unobservable local store scheduling
are not required to match the compiler's layout.

Cases include all byte values for table payloads/selectors, bank boundaries,
zero/maximum counts, upper argument bits, overlapping arrays, signed capacitor
edges, partial success/failure sequences and changing state/MMIO reads. C3 raw
counts above 255 are excluded from this finite harness because the original
byte-index loop cannot terminate; source retains its comparison. S3's count
argument is narrowed. Scripted busy reads eventually clear the busy bit; the
source loop remains unbounded, as in the original.

The six-byte state callback and wider PLL/bias/offset calls are opaque modeled
boundaries. These checks establish behavior only for the recorded cases and
models. They do not establish RF accuracy, timing, complete-domain equivalence
or device reliability. Native emitted-code and device checks are separate.
