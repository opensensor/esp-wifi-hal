# RF IQ instruction comparison

The fixtures contain `rfcal_rxiq` and `get_rfcal_rxiq_data` from the preceding
IQ conversion milestone. `baselines.json` pins the ELF/map hashes. `extract.py`
re-extracts reachable instructions, exact code bytes, literals and the diagnostic
format. No network configuration or live calibration state is included.

`machine.py` executes the original C3/S3 instructions. A collection call executes
the actual nested RF wrapper. Tone start/stop, the preceding IQ correction,
the absolute-value table callback and logging are explicit modeled boundaries.
The model varies MMIO and callback-table generations between calls. It poisons
caller registers and records ordered accesses, arguments, callback results,
private buffer bytes and the packed return. Only consumed private byte pointers
are canonicalized; S3's reversed private magnitude/phase layout is preserved.

Run `../run-phy-rf-iq.sh`. The independent Rust runner calls the production
implementation at optimization levels 0 and 2. There are 5,031 cases per chip:
2,740 conservative full-byte cases and 2,291 with correction outputs restricted
to the preceding IQ implementation's proven −31…31 range. Both classes include
logging, changing callback tables, signed full-width callback returns, argument
narrowing, convergence and four-sample averaging. Conservative cases also cover
the clamp paths and output aliasing with MMIO or the callback-table global.

The conservative interface covers all original instructions and conditional
edges: C3 162/18; S3 119/10. Under the narrower output range, four C3 clamp
instructions and their four entering edges are unreachable. All S3 instructions
and edges remain covered because its clamps use min/max instructions. The
range-constrained cases model the correction output contract; they do not execute
the IQ estimator, prove simultaneous composition, or imply that every synthetic
sample sequence is physically realizable.

Twelve focused checks test corrupted evidence, unknown instructions, uninitialized
reads, bounded-case rejection, signed ties, phase-only nonconvergence, callback
width, changing tables, S3 narrowing, aliasing and private pointer order. Python
checks also run with `-O`. Native emitted code and hardware trials require
separate validation; this oracle makes no cycle or analog equivalence claim.
