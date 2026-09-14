# RX gain-calibration oracle

Run `sh docs/network/tests/run-phy-rx-gain-cal.sh` from the repository root.
Read [the contract and bounds](../../PHY-RX-GAIN-CAL.md) first.

The manifest pins the original ELF/map hashes, function bytes, relevant readonly
tables, printf formats and extraction/engine code. The separate state model
checks original machine instructions; the host runner imports production Rust.
Ordered traces include MMIO, caller/parameter memory, callback targets, arguments,
results and private helper-buffer contents at the call boundary.

The C3 original has one unreachable upper-clamp instruction/edge, justified by
an exhaustive four-attempt state-space proof. The expected report records that
specific exemption. No automatic coverage waiver applies to emitted Rust.
Other helpers are separately verified boundaries; analog and RF effects are
not simulated by this corpus. Private stack scheduling and fixed ROM memcpy
of immutable tables are outside the trace equivalence definition.
