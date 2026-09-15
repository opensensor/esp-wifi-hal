# TX power-detector reference calibration

`pwdet_ref_code` and `pwdet_code_cal` resolve to Rust on C3 and S3. The other
sixteen TX-calibration routines per chip retain vendor ownership. Earlier RX
calibration replacements, ROM boundaries and FoA/sys pins remain unchanged.

Reference calibration narrows its single machine argument to a byte, then
calls `start_tx_tone_step(1,128,code,0,0,0)`. It preserves a fresh upper halfword
of `0x6000e05c` while selecting low-halfword patterns zero, `0x5555` and `0xaaaa`.
Between those writes, two calls to `get_tone_sar_dout(4)` supply low-halfword
samples stored at parameter offsets 218 and 220. It leaves the tone running.

Both first-sample paths read the register before storing the sample. At the
second sample, C3 reads before storing; S3 stores before reading. Volatile
halfword/word accesses preserve those architecture-specific sequences.

The no-argument calibration wrapper first reads bit 24 of parameter word
`+0x120`. An already-set bit returns immediately. Otherwise it enters TX debug
mode, performs reference calibration with code 120 on C3 or 80 on S3, restores
work mode and sets bit 24 from a fresh flag read. This preserves helper changes
to other flag bits. Existing RF initialization invokes this wrapper as void.

The [oracle](tests/phy-tx-detector-oracle/README.md) compares original code,
independent control flow and production Rust against 1,040 cases per chip.
Every original instruction and conditional edge is covered. Scripted helpers
mutate registers, flags and samples to detect cached reads and changed order.
Their results describe a software boundary, not an analog measurement model.

The composed ownership gate requires the two selected original text/literal
inputs to disappear, verifies source aliases and executable body extents, and
retains all sixteen other TX bodies in `phy_tx_cal.o`. It also runs all earlier
source gates, including complete RX-member absence on both chips.

Application-profile and paired device results will be recorded separately.
The passive lifetime probe records entry bindings, not per-call execution
counts. Keep logging and radio policy fixed when comparing implementations;
no packet-loss, cycle-timing or RF-equivalence claim follows from compilation.
