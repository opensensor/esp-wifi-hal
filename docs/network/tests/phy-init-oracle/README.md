# Initialization instruction oracle

The fixture records every reachable instruction of the 15 C3 and 16 S3 live
`phy_init.o` entrypoints in the pinned TX-gain milestone images. It contains 1,178
C3 and 1,075 S3 instructions. `baselines.json` pins the ELF, map, and complete
fixture hashes; each function also has a body hash and byte-checked instruction
encodings. `initial-state.json` records the original parameter bytes, independently
checked against the archive object and linked ELF. The two dead ROM definitions
sharing the original IRAM input are not counted as live functions.

Run `sh docs/network/tests/run-phy-init.sh` from the repository root. The Python
interpreter executes the original instructions and creates a hash-pinned binary
case stream. A separate Rust memory/callback model runs the production generic
implementation at optimization levels 0 and 2 against that stream. The 1,600 C3
and 1,675 S3 cases reach every recorded instruction and both outcomes of all
110 C3 and 92 S3 conditional edges. They include cold/warm initialization, null
input defaults, calibration checksums, ROM-version byte truncation, signed power
limits, callback-table changes, shared-state changes, actual nested local
initialization/RF/BB calls, and a fixed-seed joint sweep.

Shared reads and writes preserve address, width, value, and order. Direct calls,
callback arguments, returns and table reloads are checked. Private stack addresses
are assigned stable tags. Consumed private input buffers are compared byte by
byte when passed to child or RF-table callbacks. `memcpy` and `memset` have only
their specified memory effects: a compiler may inline initialization of private
storage. Copies into shared storage remain explicit events. The bytes consumed
by subsequent instructions or boundary calls still determine the result.

Only argument 2 of `phy_rfcal_data_check` is normalized to zero in child call
records: neither original chip implementation reads that input pointer, and LLVM
can omit its outgoing register. Other arguments remain checked. Mocked local
results stay within their independently implemented ranges: check returns 0/1,
comparison returns 0..45, and package extraction returns 0..7. These restrictions
allow the same interprocedural range assumptions as the emitted Rust firmware.
The individual original implementations and nested cases exercise those ranges.

ROM routines and retained calibration helpers are explicit boundaries. Synthetic
callback results and perturbations are tests of the caller contract, not models
of RF calibration. The model does not simulate interrupts, analog behavior, cache
disabling, radio timing, or Bluetooth operation. Native instruction comparisons,
link ownership, and paired hardware trials provide separate evidence; none alone
establishes cycle equivalence or eliminates packet loss.
