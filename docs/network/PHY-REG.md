# PHY register programming

[Production Rust](../../esp-wifi-hal/src/phy_reg.rs) provides all 16 allocated
`phy_reg.o` entries per ESP32-C3/ESP32-S3 in the tested station profile, following
[hardware frequency control](PHY-HW-FREQ.md). Strong linker assignments redirect
internal calls, external references and callback installation. Complete member
removal, including unnamed retained IRAM bytes, is checked by
[the allocation audit](tests/audit_phy_reg.py).

The member covers PBUS register copies, AGC/11b options, FE I2C renewal, Wi-Fi
enable, TX/RX IQ coefficients, tone start/stop, frequency correction and force
TX/RX off. C3 includes PA-on setup; S3 includes 14-byte digital gain programming.
Nine entries per chip and their native dependencies must remain cache independent.

The implementation preserves fresh register reads, including discarded reads;
interleaved parameter/buffer loads and MMIO writes; callback table reloads;
chip-specific argument narrowing; signed division and wrapping arithmetic; and
the two separate one-microsecond force-off delays. S3's noise-floor entry remains
a no-op. IQ wrappers return the observed result-register bits: C3 sign extends
negative results while S3 zero extends the low byte. They accept raw machine
arguments so the replacement does not invent a narrower source ABI for callers.

The host gate executes the hash-pinned original instructions against an independent
memory/callback environment and compares their complete ordered effects and IQ
results to the production Rust at O0/O2. Each chip has 4,500 cases, reaching all
619/774 recorded instructions and all 42 conditional edges. Tests include full
signed-byte coefficient sweeps, raw-width and division boundaries, unaligned
input, state mutations after MMIO and callbacks, and opaque/executed child calls.
Twenty focused oracle checks and source/vendor allocation regressions retain
explicit failure paths. Earlier audits still require vendor stop_tx_tone unless
the caller explicitly enables and validates this source stage.

```sh
sh docs/network/tests/run-phy-reg.sh
python3 docs/network/tests/test_audit_phy_reg.py
python3 -O docs/network/tests/test_audit_phy_reg.py
```

ROM, PHY-owned state, initialization, RX/TX gain and RX/TX calibration remain
dependencies. Host comparison and ownership checks alone do not establish native
ABI, board behavior, or packet-loss/timing improvement. Paired native/device
validation is recorded separately when complete.
