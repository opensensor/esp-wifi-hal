# TX detector original-instruction comparison

The fixtures pin `pwdet_ref_code` and `pwdet_code_cal` from C3/S3 linked
applications. Their ELF/map hashes and byte-checked reachable instructions are
recorded alongside the original helper addresses and Xtensa literals.

`verify.py` executes the original instructions and an independently expressed
control flow against identical scripted helper boundaries. All 1,040 cases per
chip agree: 63 C3 / 50 S3 original instructions and both conditional edges are
covered. Cases cover every byte code, high-word narrowing, both calibration-bit
states, word/halfword return boundaries and helper mutations of all relevant
state. Private ABI spills are excluded; MMIO and parameter widths/order remain
in the trace. Helpers remain separately tested software/analog boundaries.

The decoder permits an explicitly declared outlined reference body in emitted
Rust fixtures. It rejects undeclared or mismatched bodies. This support does
not exempt any reachable instruction from the native comparisons.

Run `sh docs/network/tests/run-phy-tx-detector.sh` from the repository root.
Eleven focused tests run under normal and optimized Python. The host runner
imports the production Rust module and compares every trace at O0/O2, using
temporary executables without modifying fixtures. `manifest.json` pins the
oracle sources and inputs. `extract.py` can re-extract a private hash-matching
ELF with the corresponding GNU objdump and pyelftools.

These finite traces do not prove calibrated RF, cycle timing, asynchronous
analog behavior or long-duration reliability. Linked application ownership and
paired hardware results belong in the separate validation report.
