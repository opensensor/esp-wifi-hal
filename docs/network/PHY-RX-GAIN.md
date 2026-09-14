# C3/S3 receive-gain programming

The C3 and S3 ports replace the five live `phy_rx_gain.o` functions with Rust:

| Original entry | Rust entry |
|---|---|
| `gen_rx_gain_table` | `__opensensor_rx_gain_generate` |
| `wr_rx_gain_mem` | `__opensensor_rx_gain_write_memory` |
| `set_rx_gain_param` | `__opensensor_rx_gain_set_param` |
| `set_rx_gain_table` | `__opensensor_rx_gain_set_table` |
| `phy_rx_table_init` | `__opensensor_rx_gain_initialize` |

The implementation follows the pinned original instructions and readonly tables.
It preserves ordered buffer/parameter/MMIO accesses, signed byte interpretation,
wrapping packed-field arithmetic, original count limits, logging arguments and
calibration calls. C3 reads packed entries using full words; S3 uses halfwords.
The two chips also differ in gain steps, table sizes, calibration arguments and
callback slots. Those differences are selected at compile time.

Callback table loads remain explicit. Calibration can replace the table between
calls; the write target captured before a read callback is intentionally retained.
Table initialization programs 79 C3 or 82 S3 entries. C3 then calls the existing
`rom_phy_reg_init`; S3 calls slot `0x248`. Both subsequently reload slot `4`.
These dependencies remain in ROM. RX gain IQ/DC calibration is now covered by
the [gain-calibration replacement](PHY-RX-GAIN-CAL.md); frequency adjustment
uses the preceding Rust replacement.

The entry wrappers preserve machine argument widths. S3 narrows the original
byte/halfword arguments where the binary did. `set_rx_gain_param` ignores its
second, fourth and fifth arguments on both chips. The native comparison masks
only those unused arguments at this internal boundary, since LLVM may omit
setting their registers. It still checks every consumed argument and effect.

Callers must supply valid aligned buffers, finite counts and gain values whose
coefficient indices fit the original five-element table. The host fixtures cover
the actual table families, signed values, packed-field cases, generator index-limit
exit and raw argument narrowing. They do not establish semantics for corrupted
pointers or inputs that would read beyond the original tables. No new production
clamp, retry, power policy or timing adjustment is introduced.

Run `sh docs/network/tests/run-phy-rx-gain.sh` for the pinned original-instruction
comparison at O0/O2. It reaches every recorded instruction and conditional edge
with 2,604 cases per chip. The original bytes, readonly tables, format strings,
ELF/map hashes and expected case-stream hashes are included. Nineteen focused
oracle tests check corruption rejection and important boundaries.

`audit_phy_rx_gain.py` extends all previous allocation gates. It requires the five
real Rust bodies and matching original aliases, rejects overlap with vendor
allocations, and rejects any remaining input from the replaced member, including
mergeable strings. It leaves ownership requirements for other members intact.

The lifetime probe observes entry addresses and post-initialization gain counts;
it does not itself start calibration or change gain settings. Host and native
instruction agreement does not establish RF equivalence, timing equivalence or
long-duration reliability. The separate paired-board validation records those
practical limits and any observed packet losses.
