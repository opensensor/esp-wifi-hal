# Original PHY wrapper instruction oracle

Run with Python 3, without a device or architecture toolchain:

```sh
python3 docs/network/tests/phy-wrapper-oracle/verify.py
python3 -O docs/network/tests/phy-wrapper-oracle/verify.py
```

The fixture records only four short instruction ranges, their original ELF
and archive hashes, the complete `phy_param` symbol sizes and one S3 address
literal. It contains no firmware image, radio calibration contents, network
settings or packet payloads. The selected linked inputs are the exact C3
`mac-retry-fixed-ten` and S3 `sta-mac-sequence` ELFs identified in
[`phy-dependencies.json`](../../phy-dependencies.json).

An independent review extracted `phy_api.o` from each pinned
`esp-wifi-sys` 0.2.0 archive with GNU `ar p`, inspected its `objdump -dr`
relocations and checked the linked `objdump -d` ranges against ELF symbol
addresses, sizes and bytes. `original-instructions.json` records the input,
member and instruction hashes. C3's relocatable AUIPC/JR becomes a two-byte
tail jump; S3's indirect call plus literal relaxes to CALL8. The USB stores
retain the same symbol-relative locations after linking.

The bounded interpreter reads the recorded instructions, verifies contiguous
byte coverage and code hashes, and rejects unknown operations, unresolved
literal reads, wrong call boundaries, out-of-bounds stores and instructions
after return. Python optimization does not disable these checks. It models
only the selected wrapper operations: Xtensa register-window housekeeping is
abstracted, and the outbound call is recorded without executing or replacing
the vendor callee. This does not validate PHY algorithms, timing or RF effects.

For each chip it exhausts all 65,536 valid pairs of byte arguments to the TX
wrapper and verifies one ordered call with those exact arguments and no data
writes. The C3 original tail jump leaves argument registers untouched; the S3
original explicitly narrows both outgoing arguments to eight bits. The source
interface is `u8` on both chips, so out-of-domain register values are not part
of the compatibility claim.

For the USB wrapper it runs all 256 low-byte input values with four different
full-parameter memory patterns, checks one byte store and guards all other
bytes and both exterior neighbors. The instruction-level extension to 256
values describes the original machine store; **the source C/Rust boolean ABI
only admits 0 and 1**. The production Rust tests must exercise those two values
over the full parameter region. The offsets are `0x323` inside 848 bytes on C3
and `0x2a6` inside 740 bytes on S3. Both stores alter vendor RAM state only;
they do not program or calibrate the PLL themselves.

`expected-results.json` fixes the normalized exhaustive trace digests. The
negative tests demonstrate rejection of corrupt instruction bytes, missing
literals, an unexpected callee and an out-of-bounds field. The production
tests import the actual Rust modules separately; this oracle never imports
or translates the replacement source.

Final firmware validation must additionally establish that the selected old
wrapper input sections are discarded, their RAM callee and parameter object
remain allocated, and initialization still succeeds on each board. Count only
live input ranges fully contained in ELF `SHF_ALLOC` sections; symbol sizes or
debug-map offsets alone are not allocation measurements. The wrapper oracle
is not a substitute for those link and hardware checks.
