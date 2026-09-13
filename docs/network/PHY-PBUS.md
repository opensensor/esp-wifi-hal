# C3/S3 PBUS implementation

The Rust implementation in `esp-wifi-hal/src/phy_pbus.rs` replaces every allocated
input from `phy_pbus.o` in the compared station firmware. The archive itself is
unchanged. This follows the [sensor lifecycle replacement](PHY-SENSOR-LIFECYCLE.md).
See [device validation](PHY-PBUS-VALIDATION.md) for the measured comparison and
remaining limitations.

| Original function | C3 | S3 |
| --- | --- | --- |
| `ram_pbus_force_mode` | Source | Not selected; original ROM force callback remains |
| `txcal_debuge_mode` | Source | Source |
| `txcal_work_mode` | Source | Source |
| `save_pbus_reg` | Source | Source |
| `set_pbus_mem` | Source | Source |

The misspelling in `txcal_debuge_mode` is the existing binary ABI name. Source
exports use `__opensensor_pbus_*`; an archive-named linker script supplies strong
assignments for the original names. This redirects both external references and
same-member calls, including `set_pbus_mem`'s final save. Section garbage
collection then removes the original functions, constants and jump table.

## Programming and state

`set_pbus_mem` writes twelve consecutive programs through the PBUS data register
at `0x600060cc` and its control register at `0x600060c8`. Each program first updates
one halfword of a range register, from `0x600060e0` through `0x600060f4`.
The implementation retains the original data words and order: 42 words on C3,
46 on S3. S3 has additional `0x1801ff` entries and a different `0x4831ff` entry;
C3's second eight-word program instead changes its second word to `0x14fdff`.

For every data word the source performs the original write, fresh control read,
address/control write, fresh control read and final control write. It does not
merge repeated accesses or insert a polling loop. Once all twelve programs have
been written, the six range registers are read and saved as individual 32-bit
values at `phy_param+0x328` on C3 or `+0x2ac` on S3.

The retained `bb_init` calls this programmer when bit 16 of the word at
`phy_param+0x120` is clear, then sets that bit. Existing initialization and wakeup
code retains ownership of when programming and restoring are needed. The source
does not clear the flag to force additional calibration.

## Calibration modes and callbacks

Debug mode snapshots the current byte index, byte gain field and halfword power
field, then calls the existing clock-enable, PBUS debug, TX-on, power-index,
DCO and power-detection helpers. Work mode calls the retained `stop_tx_tone(1)`,
disables the TX clock, selects RX-on with zero, and selects PBUS work mode.
Each callback obtains a fresh `g_phyFuns` pointer and slot. The source preserves
the original ordering of state reads, which differs between C3 and S3.

| Operation | C3 slot | S3 slot |
| --- | --- | --- |
| TX clock | `0x50` | `0x44` |
| PBUS debug | `0x1d4` | `0x1b0` |
| TX-on | `0x1ec` | `0x1c8` |
| Power to index | `0xec` | `0xdc` |
| DCO pointer | `0x1f0` | `0x1cc` |
| Power detector enable | `0xfc` | `0xe8` |
| RX-on | `0x1e4` | `0x1c0` |
| PBUS work | `0x1d8` | `0x1b4` |
| Force mode, called by ROM PBUS debug/work | `0x1c0` | `0x19c` |

The DCO pointer is `phy_param+0x124+8*index`, with 32-bit wrapping address
arithmetic. C3 uses the complete callback result; S3 explicitly narrows it to
16 bits. The retained ROM DCO helper reads four halfwords. The observed ROM
index helper returns 0 through 4; host tests also exercise arbitrary opaque
results to check the caller's address arithmetic without dereferencing invalid
pointers. This does not promise that arbitrary results are safe for the ROM
callee.

The native adapter retains the observed scalar argument widths. C3 callback
arguments use full 32-bit registers. S3 clock input uses a byte, TX-on uses two
halfwords, and RX-on and power-index input use a halfword. `stop_tx_tone` retains
its full-width input on both chips. These widths come from native instruction
behavior; original C typedef names and signedness are not recovered.

C3's source force-mode helper tests the entire input register for nonzero.
On entry it clears bit 27 at `0x6000610c`, then sets bit 0 at `0x60006104`.
On exit it reverses those controls in the original order. If `0x6002600c` bit 1
is set, it delays 1 microsecond, programs and pulses `0x6001c02c`, delays
2 microseconds, and clears the pulse bit using another fresh read. S3 keeps its
original ROM force implementation. There is no added interrupt, tracking task
or change to driver timing policy.

## Verification boundaries

The [instruction oracle](tests/phy-pbus-oracle/README.md) extracts the selected
functions, literal values, constants and jump targets from pinned original
linked ELFs. It interprets the original instructions independently of the Rust
source. Tests compare ordered register/state accesses, callback selection,
callback arguments and delays, including changing register reads and callback
table/state mutations. The production generic code is tested at optimization
levels 0 and 2; the native adapters and final linked images receive separate
review. S3 extraction restarts at reachable branch targets so return padding is
not decoded as instructions.

Run the host comparison and allocation regressions with:

```sh
sh docs/network/tests/run-phy-pbus.sh
python3 docs/network/tests/test_audit_phy_pbus.py
python3 -O docs/network/tests/test_audit_phy_pbus.py
```

`audit_phy_pbus.py --expect-pbus source` requires all allocated `phy_pbus.o`
inputs to disappear and all selected aliases to resolve to allocated source
bodies. It also requires the previous formatter, wrapper, dispatcher,
temperature, sensor lifecycle and no-`libpp.a` gates. The vendor mode checks a
control image with those previous replacements and the original PBUS member.
This is the station/tracking profile; a lifetime-only image may discard unused
tracking code and is reviewed separately.

The lifetime device probe reads, but does not alter, the six saved/live PBUS
ranges and initialization flag after each ordinary PHY enable. It checks the
C3 force callback's installation and records S3's retained ROM destination.
Calibration output, shutdown state and post-wakeup reception remain checked.

This removes one allocated archive member, not the PHY as a whole. ROM PBUS
read/write, debug/work, TX/RX-on, clock, DCO, power detector and index helpers
remain, as do vendor PHY state, `bb_init`, `stop_tx_tone`, RF initialization,
channel/PLL work and RX/TX calibration. Host comparisons do not establish
analog equivalence, instruction-cycle equivalence, all RF operating conditions
or compliance measurements. Runtime evidence applies to the tested devices and
conditions only.
