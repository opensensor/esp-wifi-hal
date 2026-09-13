# C3/S3 RC measurement and calibration

The C3 and S3 builds replace both functions and all allocated data from
`phy_analog_cal.o` with [Rust source](../../esp-wifi-hal/src/phy_analog.rs).
The strong linker aliases retain the original `get_rc_dout` and `rc_cal`
entry names. C3 also retains `wifi_ht20` and `wifi_ht40` as writable, aligned
16-bit objects initialized to 155 and 355. S3 uses the original immediate
divisors and exports neither object.

This follows the [power-detector replacement](PHY-PWDET.md). The ordinary
and GTK source images have nine remaining allocated PHY archive members.
ROM analog access and soft-double arithmetic remain dependencies.

## Measurement boundary

`get_rc_dout` performs the original nine masked writes, a 100-us ROM delay,
and one masked read. Every callback reloads `g_phyFuns` and its slot. C3
uses slots `0x1b8`/`0x1bc`; S3 uses `0x194`/`0x198`. The selector narrows to
its low byte. Values 1 and 2 select 7 and 6; C3 additionally maps 3 to 13.
Other values select 11. The raw 32-bit read result survives the two cleanup
writes without narrowing.

## Calibration boundary

`rc_cal` returns immediately if bit 23 of `phy_param + 0x120` is set. On
first calibration it reads the mode and any C3 divisor globals before calling
the measurement entry with the byte at `+0xf3`. The raw result's low byte is
stored at `+0x166`; the numerator uses wrapping 32-bit `(sample + 56) * 82`.

Integer division truncates signed values toward zero. Subtraction narrows to
signed 16 bits **before** clamping to 2–63. A zero C3 mutable divisor preserves
the original RISC-V DIV result of -1. The two floating-point paths explicitly
call the same ROM int-to-double, division, subtraction and double-to-int
functions. They reuse the first conversion's raw 64-bit result. Divisors are
260.0 and chip-specific 156.0 (C3) or 197.6 (S3); both subtract 8.0. The
remaining shared coefficient comes from integer division by 312. Eight
coefficient bytes are stored in original order at `+0x167` through `+0x16e`.
A fresh flag read precedes setting the completion bit.

## Validation and limits

[The instruction oracle](tests/phy-analog-oracle/README.md) compares 541,656
cases against production at O0 and O2. Native checks compare 340 diagnostic
cases per emitted source profile, including register clobbers and 64-bit ROM
arguments/returns. Full station/GTK allocation audits compose all earlier
ownership gates and reject any remaining analog member input, including
literals, data and mergeable strings. C3 data aliases are checked separately
from executable function bodies.

The lifetime probe observes normal calibration, validates coefficient bounds,
and calls only the already-calibrated early return. It adds no extra RC
measurement or analog programming. Device tests cover lifecycle, RX, station
traffic and GTK rotation using paired control/source images. See the
[device comparison](PHY-ANALOG-VALIDATION.md) for measured results and hashes.

Stack layouts, instruction counts, barriers and placement differ from the
original. The oracle does not establish timing or analog equivalence. Board
coverage is one device per chip, one AP and room conditions. RF accuracy,
other temperatures, sleep/coexistence and long-duration reliability require
further work. Packet-loss and latency investigations remain open.
