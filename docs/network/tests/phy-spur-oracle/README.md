# S3 spur instruction oracle

`esp32s3-baseline.json` pins the original linked ELF/map, the two selected
functions, external helpers and the exact log format. `extract.py` follows all
reachable instructions and verifies their bytes; the resulting fixture covers
622 body bytes / 237 instructions. Literal inputs bring the original member's
ordinary-profile allocation to 650 bytes.

`verify_contract.py` executes the original instructions and compares their
ordered observable traces with an independent model. All 4,308 cases agree and
cover every original instruction and all 30 conditional edges. Seventeen
focused tests exercise machine and boundary semantics independently of the
generated digest. `generate.py` emits the original traces for the host runner,
which imports the production Rust implementation and checks O0 and O2 builds.

The executor's Xtensa `quos` handler preserves signed truncation, overflow
wrapping and a zero-divisor exception before the destination write. It does
not use RISC-V divide-by-zero behavior. See section 8.3.242 of the
[Cadence ISA reference](https://www.cadence.com/content/dam/cadence-www/global/en_US/documents/tools/silicon-solutions/compute-ip/isa-summary.pdf).
Exception handling after that boundary and memory-barrier timing are outside
the model. Callback fixtures change targets and parameter inputs between calls.

Run `sh docs/network/tests/run-phy-spur.sh` from the repository root. The
manifest pins all oracle inputs and tools. Extraction requires the private
original ELF, pyelftools, and Xtensa GNU objdump; ordinary host comparison needs
only Python and Rust. [Implementation notes](../../PHY-SPUR.md) describe the
ABI, dependencies and interpretation limits.
