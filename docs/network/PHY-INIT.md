# C3/S3 PHY initialization

The Rust implementation replaces all live `phy_init.o` entrypoints in the tested
C3 and S3 images, including initial PHY state. It preserves the original chip
branches, callback-table installation, initialization parameters, calibration-data
transfer/checksum/recovery, RF/baseband orchestration, wakeup and shutdown.
It continues to call the retained calibration members and chip ROM.

| Area | C3 | S3 |
|---|---|---|
| Live initialization functions | 15 | 16 |
| `phy_param` initial bytes | 848 | 740 |
| `chip7_phy_init_ctrl` zeroed bytes | 42 | 42 |
| `g_phyFuns` pointer bytes | 4 | 4 |
| Additional local version state | One zeroed byte | None |
| Package/power-limit helpers | Original C3 path | Three S3 helpers |
| Remaining vendor PHY members | RX and TX calibration | RX and TX calibration |

`esp-wifi-hal/src/phy_init.rs` contains the generic implementation;
`phy_init_native.rs` supplies volatile native access, ABI wrappers and state.
Strong linker aliases preserve original symbol names while selecting the new
bodies and actual state owners. Wakeup and shutdown remain in IRAM. The linker
removes the entire original member, including dead definitions that shared its
IRAM input; those dead definitions are not counted as live replacements.

The callback table retains the original ROM-version handling. On C3 the version
query is narrowed to a byte before selecting the patch group; zero and nonzero
versions use different installed functions. S3 preserves package-specific power
limits and its separate register and parameter ordering. Calibration callers
retain the original buffer extents, checksum representation and save/recovery
order. Internal state access requires the existing PHY serialization.

The initialization buffer defaults come directly from independently checked
object and linked-image bytes. This establishes initial storage contents; it is
not a claim that calibrated runtime state is constant or chip-independent.
`phy_init_ownership.py` makes the state transition explicit in earlier ownership
gates. Earlier gates remain strict unless that transition is requested and the
new code/state bodies, aliases, extents and hashes pass their own checks.

The [instruction oracle](tests/phy-init-oracle/README.md) explains the independent
fixture, perturbations, consumed-buffer checks and limited ABI normalization.
Run `sh docs/network/tests/run-phy-init.sh` for the original-instruction comparison
against production Rust at O0/O2. Native emitted instructions, link ownership,
IRAM placement, and hardware behavior are separate checks.

This work replaces initialization orchestration, not the RF calibration routines
called by that orchestration. Analog equivalence, Bluetooth operation, cache-off
transitive safety, long-duration reliability and packet-specific latency/loss
causes still require separate investigation. Earlier packet-loss observations
remain recorded in the prior milestone reports.
