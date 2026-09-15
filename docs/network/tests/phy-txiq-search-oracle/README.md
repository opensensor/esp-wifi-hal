# TX IQ correction search and calibration

`txiq_cover` and `rfcal_txiq` are compared with pinned original C3/S3
instructions. Run `sh docs/network/tests/run-phy-txiq-search.sh` from the
repository root. Each chip has 1,616 cases; the independent Python model and
actual Rust implementation at optimization levels 0 and 2 must match ordered
memory accesses, callback arguments and final state. Every original instruction
and conditional edge must execute. Checks also run with Python assertions off.

The search covers four-round early termination and seven-round exhaustion,
signed 16-bit measurements, zero-denominator guards, signed-byte accumulation,
full callback return words, and all attenuation bytes. Each helper can change
registers, output bytes, parameters, the live callback table and its slots.
The corpus preserves C3/S3 differences in argument narrowing, sample-read order,
intermediate output access order, final stores, and correction return narrowing.

Calibration covers mode and chip-specific narrowing, the C3 parameter selector
and offset, mode 1's saved PBUS writer, mode 2's loopback and DC calibration,
coefficient clamps, packing, and restoration of the saved register word.
Caller buffers include aliasing at aligned offsets within the supplied extent.
No helper's arithmetic or analog behavior is inferred from its test stub.

The ABI contract is a writable two-byte output for `txiq_cover`. `rfcal_txiq`
receives an aligned eight-byte DC buffer (input for modes 0/1, output for mode 2)
and an aligned writable two-byte IQ output. The search's measurement helper
initializes two aligned halfwords. The calibration helper's search initializes
two coefficient bytes. Native scratch is uninitialized until those calls and
then accessed with volatile reads/writes to preserve the original ordering.
The existing initialization and Bluetooth wrappers ignore both return values.
ROM abs, PBUS, DCO and loopback callbacks remain live table dispatches.

The oracle compares calibration with search as an explicit helper boundary;
it separately executes the complete selected search. Unknown calls, invalid or
uninitialized accesses, malformed instructions and incomplete coverage fail.
Extraction follows reachable code and checks instruction/body hashes. Final
emitted native firmware bodies are compared separately before device trials.

These checks establish behavior at the declared helper boundary, not analog
calibration quality. Wi-Fi device tests do not establish Bluetooth RF behavior.
