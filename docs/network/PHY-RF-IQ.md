# Receive RF IQ orchestration

C3 and S3 replace `rfcal_rxiq` and `get_rfcal_rxiq_data` with Rust. The first
sets up the receive calibration register, starts the tone, calls the existing
IQ correction, stops the tone and copies its two output bytes. The second
takes at most four samples, stopping when two successive magnitude and phase
differences are at most one. It rounds the chosen average, clamps both signed
bytes to −31…31 and packs two six-bit coefficients.

The implementation preserves ordered volatile accesses, signed rounding, the
full signed callback result, and table reloads between difference checks.
S3 narrows mode/gain/logging to bytes and frequency to signed 16 bits; C3
retains incoming words. The tone, correction and callback implementations
remain explicit dependencies. No timing or logging changes accompany this slice.

Strong aliases select both source functions. The composed allocation gate
rejects surviving original text/literal inputs and still requires the six C3
or eight S3 remaining RX calibration bodies. Earlier gates retain their strict
defaults; the new gate explicitly permits only this ownership transition.

See the [instruction comparison](tests/phy-rf-iq-oracle/README.md) and
[paired validation](PHY-RF-IQ-VALIDATION.md). Receive DC
and gain searches, S3 spur routines, transmit calibration and ROM/analog
dependencies remain. Instruction equivalence under the documented boundaries
does not establish analog accuracy or explain packet loss.
