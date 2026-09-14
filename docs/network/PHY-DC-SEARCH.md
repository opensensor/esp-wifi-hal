# Receive DC searches

C3 and S3 use Rust for `pbus_rx_dco_cal` and their respective
`pbus_rx_dco_cal_1step_new` / `pbus_rx_dco_cal_1step` entry points.
The five-argument general search processes two sequential pairs of signed
halfword coefficients. The six-argument one-step search updates one pair, a
three-word estimate buffer and a status byte. The coefficient pointers need
only two-byte alignment; no Rust references impose exclusive ownership on
caller buffers.

The implementation preserves signed 16-bit wrapping before clamping,
32-bit wrapping multiplies/subtractions and arithmetic shifts, truncation
toward zero for division, two-bank initialization, loop exhaustion and the
last *written* coefficients. C3 retains full scalar inputs; S3 narrows its
sample count/delay to u16 and policy/mode/log flags to u8. The one-step
threshold is six on C3 or ten on S3 for the nonzero-policy, non-one mode;
the iteration budgets are eight or sixteen, separately. General search
budgets are twelve and four. The full signed difference callback result is
used, including C3's otherwise unused extra calls. S3 and C3 retain their
different externally visible output-store order.

Every PBUS, estimator, difference and limiter call obtains its target from
the live callback table. These helpers, ROM delay and the separately tested
minimum-selector function remain boundaries. The minimum selector's middle
argument is unused, as established by its existing implementation and
RX-DC tests. Native compilation can leave that argument register unspecified;
the search oracle canonicalizes that one ignored value. It does not erase
sample counts, buffer addresses, helper identity or other callback arguments.

The six-byte coarse table is `[80, 71, 63, 56, 50, 44]`. Its source bytes are
pinned against the ELF and linker map, including images whose local table
symbol was stripped. The supported calibration input domain requires the
PBUS-derived coarse index to be 0 through 5. Out-of-range synthetic indices
are rejected by the oracle; neighboring vendor bytes are not invented as
additional entries. The unsafe native ABI inherits this precondition. This
is a bounded contract, not a proof of every physically possible PBUS state.

## Regression evidence

`tests/phy-dc-search-oracle` contains the pinned original instruction bodies,
readonly bytes, printf formats, helper symbols, ELF/map hashes, a separate
state model and instruction executor. The corpus has 2,016 cases per chip,
covering every original instruction and conditional edge: 664/122 for C3
and 656/100 for S3. Cases cover convergence/exhaustion, signed boundaries,
policy narrowing, callback-table changes, callback memory mutations and
aliased caller buffers. Fifteen oracle tests include invalid table domains,
wrong signed narrowing, callback caching, fixed-width overflow, buffer
alignment, exhaustion stores and the SLTI/SGTZ predicates.

The host runner imports the production Rust module at optimization levels
zero and two, comparing ordered traces from original machine instructions.
Traces retain caller-buffer reads/writes and helper calls/results. Private
stack spills, compiler scheduling of private loads and immutable table loads
are excluded. Callback target generations still detect cached dispatch.
The test callbacks initialize all three estimator output words.

`audit_phy_dc_search.py` composes all earlier ownership gates and verifies
both source aliases, executable body extents, absence of the selected vendor
sections and preservation of the other calibration bodies. Earlier gates
require an explicit DC-search transition; their default requirements are
unchanged. Remaining RX bodies are gain IQ/DC calibration on both chips and
two spur helpers on S3. TX calibration and analog/ROM dependencies remain.

Device comparison and native emitted-code results are recorded separately
when completed. These synthetic boundary tests do not establish analog/RF,
cycle-count, long-duration or packet-loss equivalence. FoA logging and network
policy remain fixed during this PHY comparison.
