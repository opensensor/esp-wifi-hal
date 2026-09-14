# Receive saturation and IQ-estimator controls

C3 and S3 now use Rust for `rfrx_sat_rst`, `phy_force_rx_gain_trig`,
`ram_iq_est_enable` and `phy_check_rx_sat`. C3's compiler-split reset tail is
inlined into the reset implementation. This is the first portion of
`phy_rx_cal.o`; its IQ conversion, DC searches, gain calibration and S3 spur
routines remain vendor dependencies, as does TX calibration and ROM.

The implementation preserves ordered volatile accesses, the one-microsecond
trigger delay, the estimator's completion polling and wrapping 16-bit counter,
and the 100-sample saturation check. A check without a qualifying sample leaves
the saturation flag unchanged. S3 narrows reset to a byte; C3 tests its full
word. The estimator's first argument is unused in both originals. Callback
pointers reload from the writable PHY table for each operation. The temporary
callback input contains the same four halfwords (`0x100`).

The production source and native bindings are `phy_rx_controls.rs` and
`phy_rx_controls_native.rs`. Strong linker aliases redirect original callers
and initialization's estimator callback. `audit_phy_rx_controls.py` composes the
previous initialization gates, rejects original code/literal allocations and
checks genuine source bodies. It also requires retained calibration bodies.

`sh docs/network/tests/run-phy-rx-controls.sh` executes pinned original
instructions and compares their ordered register/state/callback traces with
production Rust at O0/O2. Cases vary reset/sample inputs, fresh MMIO reads,
callback-table generations, completion sequences and counter overflow. Every
recorded original instruction and conditional edge must execute. Native builds
require separate checks against emitted instructions and actual ELF constants.

These are finite software and hardware checks, not calibrated RF measurements
or proof of analog or cycle equivalence. Completion polling intentionally retains
the original behavior; this change does not introduce a hardware timeout policy.
