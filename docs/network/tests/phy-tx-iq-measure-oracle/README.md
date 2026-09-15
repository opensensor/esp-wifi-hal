# TX IQ measurement and attenuation oracle

Run `sh docs/network/tests/run-phy-tx-iq-measure.sh` from the repository root.
Python's standard library and Rust are sufficient for the host comparisons.
`extract.py` additionally needs pyelftools and the matching GNU objdump to
re-extract the pinned private firmware. No firmware or network credentials
are included here.

The original `txiq_get_mis_pwr` and `get_power_atten` instructions were extracted
from C3/S3 ordinary applications at implementation
`efb1816480bfa10f11ef14b81ced021e4a5bb1b6`. Per-chip baseline files pin the
whole ELF/map hashes, function extents, helper addresses and readonly format.
The instruction files preserve complete selected bodies and reachable PCs.
The comparison runs 1,654 cases per chip: 177 C3 / 130 S3 instructions and
18 conditional edges each, plus the production Rust model at host O0/O2.
Expected coverage and trace digests are checked explicitly, including under
optimized Python. Helpers have scripted effects on registers, outputs and the
live callback table. This checks access width/order and arithmetic at those
boundaries; it does not simulate analog RF or physical timing.

Measurement preserves fresh register reads, two 2us delay/sample pairs and
ordered low-halfword output stores, including aliased output addresses. S3
narrows select/offset at entry; C3 preserves the supplied words. Attenuation
preserves six attempts, signed-halfword arithmetic, backoff before logging,
convergence at delta -3..3, signed truncation for negative adjustments and
the final possibly unmeasured adjustment. S3 has an extra 2us delay and uses
delta directly. C3 reloads `g_phyFuns` and slot +40 for `(delta,20,-20)` on
each unconverged iteration. Neither path adds tone cleanup.

Four direct caller windows per chip establish argument order and valid
halfword output storage. Attenuation callers consume byte results, but the
replacement preserves the complete word return. Installed C3 ROM reference
ELFs (revisions 0, 3 and 101, package 20241011) identify the initial +40 slot
as a signed three-argument clamp; the replacement retains live dispatch.
This reference evidence is not a fresh board callback-table measurement.

Final application comparisons and device validation are recorded separately
in the TX IQ measurement validation report. The sixteen remaining vendor TX
routines before this pair become fourteen per chip. Other helpers and ROM
dependencies remain explicit; this is not complete PHY blob removal.
