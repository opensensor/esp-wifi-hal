# C3/S3 hardware frequency control

[Rust](../../esp-wifi-hal/src/phy_hw_freq.rs) provides all 11 functions per chip
from `phy_hw_freq.o`, following the [RF PLL replacement](PHY-RFPLL.md). Strong
linker aliases retain the original entry names. Busy polling and hardware
frequency enable/disable stay in IRAM; the table-building and channel helpers
remain in flash. Wider RF PLL, calibration, gain, ROM and state dependencies
remain explicit call boundaries.

## Preserved behavior

- Busy polling has no timeout or added delay. Disabling hardware frequency
  sets control bit 25 and delays two microseconds; enabling clears that bit.
- Frequency-memory programming writes three words and pulses control bit 9
  using fresh MMIO reads. C3 loads each buffer word before the control read;
  S3 reads the control register first. Selectors wrap modulo 256.
- The I2C interface retains nine arguments, including incoming stack arguments.
  Count fields, enable bits, host nibbles, register/block pairs, selector flags
  and data bytes retain their original widths, bank selection and ordering.
  C3/S3 differ in several buffer-versus-MMIO read orders. Selectors outside the
  four byte-data banks do not program a data byte.
- Capacitor-memory correction updates all 85 entries. Its signed high-bit
  promotion and 16-bit intermediate wrap are retained without a new clamp.
- Initial frequency construction preserves its done flag, three reference
  frequencies, signed capacitor interpolation, 85 memory entries, callback
  reloads and temporary buffer contents. The final flag/offset store order
  differs between chips. S3 writes the initial capacitor through its callback;
  C3 uses the direct entry.
- I2C data collection preserves all output-write ordering, including aliased
  buffers, two raw callback values and the six-byte state callback. Row nine
  has host flag 1 on C3 and 0 on S3. Even a zero-count call performs the initial
  callbacks; entries beyond row nine only clear their enable byte.
- Software channel switching preserves offset/mode narrowing, unmasked
  channel-bit insertion, separate busy waits, a one-microsecond delay and at
  most three channel observations. The final capacitor value is saved even
  when none of those observations matches.

## Verification

The [instruction oracle](tests/phy-hw-freq-oracle/README.md) compares production
Rust at O0 and O2 against 1,418 C3 and 1,442 S3 cases. All 927 C3 / 1,039 S3
recorded instructions, both edges of all 30/29 conditional branches, and every
jump-table destination are reached. Twenty-nine focused tests exercise ABI,
ordering, retry behavior and malformed evidence. A separate deterministic joint
sweep adds 704 cases per chip at both optimization levels.

The allocation gate composes the RF PLL and preceding source gates. It rejects
any allocated member code, data, literals or excluded mergeable strings, checks
every alias against a real source body, and rejects the three IRAM helpers if
they move to flash. All 225 allocation regressions run normally and under
Python -O. The passive lifetime probe observes entry addresses, callback slots
and state after ordinary PHY initialization; it does not start another RF
operation or busy wait.

These are bounded software comparisons. C3's raw counts above 255 cannot
terminate the original byte-index comparison and are outside the harness's
finite domain; production does not add a clamp. S3 narrows count to a byte.
Modeled callbacks can mutate buffers, state and table generations, but this does
not validate the opaque callback bodies, calibrated RF behavior, cycle timing,
other temperatures, sleep/coexistence or long-duration reliability. Device
comparisons and packet-loss findings must be assessed separately.

This continues the initial local Qwen3.8-flash-next / closed-source re-framework
reconstruction with manual Rust correction, instruction comparison and device
validation. OpenSensor Engineering is available for additional reverse-engineering
and embedded contract work.
