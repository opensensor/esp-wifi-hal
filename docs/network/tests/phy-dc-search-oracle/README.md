# Receive DC-search oracle

See [the implementation contract](../../PHY-DC-SEARCH.md).

Run `sh docs/network/tests/run-phy-dc-search.sh` from the repository root.
The suite requires Python 3 and Rust; ELF re-extraction additionally requires
pyelftools, the pinned private ELF and the appropriate GNU objdump.

`manifest.json` binds instruction/readonly/helper fixtures to their ELF/map
hashes and extraction/engine hashes. `expected-results.json` records the
original instruction coverage and ordered-trace digests. The host test
imports production Rust; no translated copy substitutes for that module.

The independent model and instruction executor share only boundary mocks and
integer-width helpers. Tests include counterexamples for cached callbacks,
wrong signed narrowing and non-wrapping coefficient arithmetic. Every original
instruction and branch edge must execute. Invalid coarse-table indices are
outside the supported input domain and must fail, including under Python -O.

Native ELF comparisons use these same cases and trace rules. The separately
validated minimum selector ignores its middle argument, which is normalized
in both original and native call traces. Other arguments, caller-buffer
accesses, callback results and live callback generations remain observable.
Private stack traffic and immutable table loads are excluded. These are
bounded software contracts, not analog/RF or timing proofs.
