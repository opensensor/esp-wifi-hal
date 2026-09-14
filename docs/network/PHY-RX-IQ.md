# Receive IQ conversion and correction

The C3 and S3 builds replace `rxiq_get_mis` and `rxiq_cover_mg_mp` with Rust.
The first converts four IQ measurements into two correction bytes. The second
programs coefficients and performs two estimation/correction rounds before
clamping its two output bytes to -31..31.

The source preserves wrapping 32-bit sums, signed 64-bit products and wrapping
shifts, signed division, and byte narrowing before rounding. S3 narrows incoming
mode/logging arguments to bytes; C3 retains their full words. Measurement reads,
output writes, logging rereads and callback-table reloads retain their original
order. Output pointers may alias. Register programming uses the existing Rust
`rxiq_set_reg`; signed-wide division and analog callbacks remain ROM boundaries.

Strong linker aliases select both source bodies. The allocation gate composes
all previous source gates, rejects surviving original text/literal inputs and
requires every remaining chip-specific RX calibration body in `phy_rx_cal.o`.
The preceding RX-control gate permits this transition only when explicitly
requested by the IQ gate. Its default still requires the original IQ bodies.

See [the instruction oracle](tests/phy-rx-iq-oracle/README.md) and
[validation results](PHY-RX-IQ-VALIDATION.md) for the scope and limitations.
RX and TX calibration search routines and ROM dependencies remain.
