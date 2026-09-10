# ESP32-S3 PHY register helpers and ROM patch selection

`s3_phy.rs` replaces the driver's low-rate initialization helper and its two
direct AGC calls with reviewed Rust register operations. AGC preserves the
original direct-call ROM behavior. A hardware comparison demonstrated why the
PHY library's internal RAM patch must not be substituted at this call site.

This is a small further reduction in binary dependencies. PHY calibration,
channel tuning and power tracking remain in `libphy.a`; the library's own RAM
AGC routines remain allocated and are still used internally. No complete PHY
replacement or packet-loss fix is claimed.

## Evidence and the two AGC contracts

The reviewed archive is `esp-wifi-sys-esp32s3` 0.2.0's `libphy.a`, SHA-256
`29dcc18a035801bd41486d5d59f3caeb62f8ed153533c488828bffef1abb99fd`.
Function addresses below refer to the earlier tested S3 station ELF, SHA-256
`9e4509483e602b6b9063358f40a2fa45ce3a3d777ff9d57b656df412cc003193`.
ROM instructions were read from Espressif's `20241011/esp32s3_rev0_rom.elf`,
SHA-256 `c0ce0f338d1de1bdc6efbef1591779a2a42c1ab7d759d3c6ae8ae63a7dd34cfd`.

| Routine | Address | Body size | Relevant behavior |
| --- | --- | --- | --- |
| `phy_disable_low_rate` | `0x42037b10` | 56 bytes | Three ordered register updates |
| `ram_disable_wifi_agc` | `0x4037b3a0` | 67 bytes | Uses `0x6001c034` |
| `ram_enable_wifi_agc` | `0x4037b3e8` | 67 bytes | Uses `0x6001c034` |
| `phy_get_romfunc_addr` | `0x42035fb0` | 203 bytes | Installs the RAM AGC pair in the PHY table |
| `chip_v7_set_chan` | `0x42038164` | 192 bytes | Calls that table around channel work |
| ROM disable body | `0x40038020` | 67 bytes | Uses `0x6001c038` |
| ROM enable body | `0x40038068` | 67 bytes | Uses `0x6001c038` |

The firmware's `rom_disable_wifi_agc` and `rom_enable_wifi_agc` symbols resolve
to ROM veneers at `0x40005fa0` and `0x40005fac`. Those veneers jump directly to
the ROM bodies; they do not consult the PHY table. In contrast,
`phy_get_romfunc_addr` unconditionally writes the RAM disable/enable pointers
to `g_phyFuns` table offsets 8 and 12. `chip_v7_set_chan` calls those patched
slots. The Rust driver's extra AGC calls in `LowLevelDriver::set_channel`
use the direct ROM contract, outside the library's internal channel call.

The first candidate followed the installed RAM implementations at `0x6001c034`.
It passed ten station reconnect cycles but failed the receive-buffer drain test
twice: after returning one of nine held buffers, the pending tenth completion
was preserved, but no new completion arrived in the returned buffer. The
unchanged baseline passed that test. Restoring only `0x6001c038` in the Rust
AGC pair restored the drain/recovery/TX test. The two candidate images have the
same layout; apart from hash/checksum metadata, their only changed byte is the
AGC register literal (`0x34` to `0x38`).

The final source therefore preserves the direct ROM call's `0x6001c038`
transactions. Internal PHY table callbacks continue using their original RAM
implementations at `0x6001c034`. The precise hardware role of this difference
is not established. A matching routine name and an installed patch table do
not establish interchangeable behavior across these caller contexts.

## Register transactions

Every row is a separate 32-bit read followed by a 32-bit write. The value
written is `(value_read & keep_mask) | set_bits`; order is significant.

| Routine | Order | Register | Keep mask | Set bits |
| --- | --- | --- | --- | --- |
| Low-rate disable | 1 | `0x6001c860` | `0xfffffbff` | `0` |
| Low-rate disable | 2 | `0x6001c860` | `0xfffff7ff` | `0` |
| Low-rate disable | 3 | `0x6001c87c` | `0xfffff7ff` | `0` |
| AGC disable | 1 | `0x6001c01c` | `0xff00ffff` | `0x007f0000` |
| AGC disable | 2 | `0x6001c038` | `0xffffffff` | `0x80` |
| AGC disable | 3 | `0x6001c080` | `0xffffffff` | `1` |
| AGC enable | 1 | `0x6001c080` | `0xfffffffe` | `0` |
| AGC enable | 2 | `0x6001c01c` | `0xff00ffff` | `0x00200000` |
| AGC enable | 3 | `0x6001c038` | `0xffffffff` | `0x80` |

The original instructions use `memw` before each MMIO load/store. Inspection
of the compiled Rust station ELF confirms the volatile accesses retain these
barriers and the transaction order. The low-rate function keeps its intervening
read of `0x6001c860`; combining the first two writes would change the contract.

## Tests and remaining dependencies

Run `sh docs/esp32s3/tests/run-rust-tests.sh`. Five PHY tests compare the Rust
access traces with expectations transcribed from the original instructions.
Each of the three routines is checked with 260 initial register patterns. An
additional test changes unrelated hardware bits between the two low-rate
writes; another verifies that a direct AGC pair leaves the internal RAM patch
register untouched. These tests check ordering, masks and unrelated-bit
preservation. They do not
model analog behavior. The existing initialization, DMA, RX, HT20 and C3
instruction-trace tests also pass.

The station comparison uses base `be22c0b` and the same ten-cycle FoA example,
toolchain, credentials and secured S3. Only the PHY source and wiring differ.
Linker allocation is counted after the map's `Linker script and memory map`
boundary, excluding discarded input sections and address-zero entries.

| Station image | Allocated `libphy.a` input bytes | Allocated members | Direct ROM AGC call sites |
| --- | --- | --- | --- |
| Baseline | 33,318 | 18 | 2 |
| Rust PHY helpers | 33,250 | 18 | 0 |

The original `phy_disable_low_rate` symbol is absent from the Rust-helper ELF.
Its input section is discarded. The net archive allocation drops by 68 bytes,
including linker relaxation differences; the old function body itself was
56 bytes. Both images still allocate `libprintf.a` (11,981 bytes, one member)
and allocate no `libpp.a` code or data. ROM linker symbols may remain defined
even without call sites; symbol existence alone is not a dependency count.
The vendor RAM AGC pair is deliberately retained for internal PHY callers.

The conservative disassembly audit resolves 36 distinct ROM entry targets in
the final station image, including memory/math/runtime helpers, PHY table
retrieval, I2C access and PHY backups. This is a lower bound: indirect function
table calls are not counted. The original driver AGC pair is the two-target
reduction; it does not remove the PHY library's own ROM dependencies.

The final ROM-contract source completed ten WPA2/IPv4/disconnect cycles with
200/200 gateway replies and 191/200 host replies. The nine missing host replies
were the first ping after reconnect, consistent with the existing smoltcp
neighbor-resolution reproduction. The unchanged baseline completed nine cycles
(180/180 gateway, 172/180 host), then connected but timed out waiting for DHCP in
cycle 10. These results preserve the known failures; they do not establish a
fix for intermittent DHCP or first-reply loss. The final smoke image received
six frames (two OFDM), preserved the unread pending descriptor, loaned out all
ten RX buffers, recovered after reverse-order returns, completed OFDM TX and
confirmed that the MAC timer advanced.

Hardware results and image hashes are recorded in
[`phy-validation.json`](phy-validation.json). Each image is signed with the
board's existing key and written only at its app slot, `0x20000`. No bootloader,
partition table, eFuse or flash-security settings are changed.
