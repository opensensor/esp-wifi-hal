# Receive DC estimate selection and channel filling

C3 `rxdc_est_min_new` and S3 `rxdc_est_min` use the Rust minimum selector;
`rx_chan_dc_sort` uses Rust on both chips. The linker retains explicit source
bodies and aliases the original entries to them. Analog estimation and the
absolute-value callback remain external. Larger DC/gain searches, S3 spur
helpers, TX calibration and ROM dependencies remain.

Minimum selection attempts at most eight estimates. It reads the callback table
again for every sample, then checks the live parameter gate only for a strictly
lower signed score. S3 narrows sample count to u16; C3 retains the full word.
The unused second argument remains in the C ABI. Scores at most 35 stop at once;
scores at most 47 stop after at least three attempts. Exhaustion overwrites the
output with score 56 and two zeros. Volatile accesses preserve observed sample,
parameter and output ordering, including aligned output/parameter overlap.

Channel filling uses one S3 column and three interleaved C3 columns. C3 carries
its selection/count state between columns: only column 0 can fall back to
status 2; later columns prefer status 1 even if none exists in their own column.
Resetting that count would change the original behavior. Distances narrow to
signed 8-bit, ties keep the earlier candidate, and data is copied in place with
mask 0xffff01ff. No immutable status/data snapshot or cached callback is used.

## Reproduction

Run `sh docs/network/tests/run-phy-rx-dc.sh` from the repository root. The host
harness imports the production Rust module; its mock supplies memory/callback
boundaries. All 2,368 C3 and 1,976 S3 cases compare ordered accesses and callbacks
against the pinned original instructions at Rust optimization levels 0 and 2.
The corpus covers all 168/101 original instructions and 30/28 conditional edges.
Nine focused tests check thresholds, gate ordering, table reload, scalar width,
C3 column state, signed-byte distance and fixture corruption, in normal and
optimized Python modes. Eleven ownership tests cover both stages and the
explicit transition through earlier source gates.

Cases include callback mutations, arbitrary signed estimator scores/distance
returns and permitted memory overlap. This conservative interface coverage is
not an analog/RF model; it does not establish that every input is physically
reachable, cycle equivalence, packet-loss improvement or calibrated behavior.
The synthetic estimator supplies all three local words before they are read.
No behavior is claimed for an estimator leaving that buffer uninitialized.

Compiled-image ownership, native instruction comparisons and fixed device
results are recorded in the
[milestone validation report](PHY-RX-DC-VALIDATION.md). Keep FoA/sys pins and
logging policy fixed when comparing PHY changes.
