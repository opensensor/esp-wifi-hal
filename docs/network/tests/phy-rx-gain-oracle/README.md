# Receive-gain original-instruction oracle

`original-instructions.json` contains byte-checked reachable instructions for all
five live receive-gain functions on each chip, plus exact readonly inputs and log
formats. Baseline images contain implementation `aaf086d` from the preceding
register milestone. `baselines.json` pins the ELF, map and complete fixture hashes.
No complete firmware, network configuration or board calibration data is included.

The interpreter executes the original instruction streams. The Rust host test
uses the production generic functions with a separately implemented access model.
The models compare ordered reads/writes, packed words, logging arguments,
calibration boundaries, fresh callback-table generations and actual child-function
execution. Optional opaque children cover result clamping separately. Only the
three unused `set_rx_gain_param` arguments are masked at that internal boundary.

The fixed cases reach all 782 C3 and 709 S3 recorded instructions and all 78/54
conditional edges respectively. `expected-results.json` pins each complete case
stream. Validation uses explicit checks, which remain active under Python `-O`.
The focused tests include fixture corruption, readonly-byte integrity, callback
reloads, captured write targets, calibration ABI, logging stack arguments, packed
read widths and generator termination.

Extract again with `extract.py --help` using the private pinned ELF and map and
the appropriate GNU objdump. Extraction reads the bytes again, checks instruction
encodings and follows reachable branches. The execution model rejects unknown
instructions, uninitialized accesses, unsupported calls and exhausted budgets.

The finite input domains preserve the original buffer requirements. The model
covers boundary effects, not CPU cycles, interrupt interleavings, analog behavior
or the contents of retained ROM/calibration routines.
