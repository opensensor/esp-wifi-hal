# Transmit gain instruction oracle

`run-phy-tx-gain.sh` validates the pinned fixture and expected case stream, runs
19 focused oracle tests normally and with Python optimization, and compares the
production Rust implementation at O0 and O2 against the original instructions.

The C3 fixture contains all 11 live transmit-gain functions (642 instructions).
The S3 fixture contains all 12 live transmit-gain functions (622 instructions),
plus the previously replaced digital register writer and basic interpolator
(90 emitted Rust instructions). These two bodies are explicit dependencies,
not additional vendor functions replaced by this milestone.

The 1,566 C3 and 1,784 S3 deterministic cases reach every recorded instruction
and both outcomes of every conditional branch: 62 C3 and 68 S3 edges, including
the S3 dependencies. Cases exercise signed narrowing, wrapping, overlapping
buffers, threshold searches, table mutation, logging and actual/opaque child
calls. The runner requires these coverage totals and the exact stream hashes.

Each record has 48 input words, a return word, a trace-length word and a sequence
of 16-word events. Traces compare ordered reads/writes to caller buffers, PHY
parameters, init control and MMIO, callback-table and slot reads, callback entry
and return, internal children, calibration boundaries and logging arguments.
Compiler-private stack accesses are excluded; pointer identities are canonicalized
and their contents are consumed by subsequent calls or observable output writes.
Readonly copies are checked against the exact pinned bytes. The original ELF and
map hashes, readonly inputs and format strings are in `baselines.json`.

The Wi-Fi table generator's twelfth argument is unused by both original bodies.
Only that argument is masked at this internal boundary. Native comparisons also
avoid reading an unset outgoing stack slot for this argument; all consumed
arguments, stack arguments, return values and observable effects remain checked.

Cases require initialized, valid and aligned buffers and finite searches. The C3
byte-index lookup excludes counts above 255; count zero is covered using its
original index-255 behavior. Wide/invalid channels are exercised with padded
caller buffers or opaque child boundaries, not against the 42-byte hardware init
control table. These tests do not define behavior for arbitrary invalid pointers.
ROM callbacks and retained calibration routines remain modeled boundaries.

`extract.py CHIP ELF OBJDUMP OUTPUT` reproduces the corresponding fixture entry
from the hash-pinned private image. It verifies instruction bytes, readonly data
and formats. Public fixtures contain no firmware image, network settings, keys,
runtime calibration state or packet payloads.

Instruction agreement is bounded behavioral evidence. It does not measure RF
power, establish timing equivalence or resolve packet loss.
