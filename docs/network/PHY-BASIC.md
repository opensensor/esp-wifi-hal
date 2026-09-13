# C3/S3 basic PHY member replacement

`esp-wifi-hal/src/phy_basic.rs` supplies the remaining selected `phy_basic.o`
helpers in Rust. Strong linker assignments remove the entire allocated
member in the compared images. The vendor archives are unchanged.

| Helper | C3 | S3 | Source placement |
| --- | --- | --- | --- |
| I2C master reset | `rom1_i2c_master_reset` | `ram_i2c_master_reset` | IRAM |
| Channel-14 configuration | `chan14_mic_cfg` | `chan14_mic_cfg` | Flash |
| Channel calibration interpolation | Not selected | `ram_set_chan_cal_interp` | Flash |

`rom_set_chan_reg` stays bound to ROM: `0x40001bec` on C3 and `0x4000633c`
on S3. Removing the archive member does not replace those ROM routines.
Retained `phy_set_most_tpw` still comes from `phy_feature.o`.

## Preserved behavior

Reset enters the existing critical section and visits `0x6000e000`, then
`0x6000e004`. If bit 25 is set, it writes **exactly** `1 << 26` and polls
bit 25 until clear before visiting the next host. It then exits the critical
section. The original has no timeout; the source preserves that behavior.
The retained entry/exit helpers currently coalesce to the same no-op address
in the pinned images. Both calls remain present.

Channel-14 configuration is enabled when the full 32-bit argument equals one
on C3, or its low byte equals one on S3. It reads `0x6001c400` once, clears
bits 13–14 and sets bit 13 when enabled, or sets both bits otherwise, then
writes the result. It reads the parameter byte at `+0xe4` when enabled or
`+0x98` otherwise and sign-extends it before calling `phy_set_most_tpw`.

S3 interpolation computes `index = (channel - 1) & 255`. For indices 0–5 it
reads calibration bytes 0 then 1, interpolating their signed difference over
five steps. For indices 6–10 it reads byte 2 then byte 1 and interpolates
their signed difference. Larger indices read only byte 2 and add two.
Division truncates toward zero, the final result wraps to a byte, and the
return value is zero-extended. The native adapter uses the caller's local
calibration pointer, with no global scratch state.

The native reset entry and its S3 literals are in IRAM. The compiler uses a
loop over the two host addresses and volatile operations; S3 also emits
memory barriers. Instruction counts and timing can differ from the original
unrolled implementation. This does not establish cycle or analog equivalence.

## Validation

The [original-instruction oracle](tests/phy-basic-oracle/README.md) compares
the actual production logic against **841,856 cases at O0 and O2**, including
ordered MMIO, polling, helper calls, byte accesses and arithmetic edge cases.
Native review separately checks ABI, aliases, placement and retained ROM
bindings. Existing ESP32/S2 compatibility builds remain separate from the
C3/S3 hardware comparison.

```sh
sh docs/network/tests/run-phy-basic.sh
python3 docs/network/tests/test_audit_phy_basic.py
python3 -O docs/network/tests/test_audit_phy_basic.py
python3 docs/network/tests/audit_phy_basic.py \
  --elf /path/source-sta_smoke.elf --map /path/source-sta_smoke.map \
  --label source --expect-basic source
```

The allocation audit composes all earlier source milestone gates, requires
no allocated `phy_basic.o` input, checks real source bodies at the selected
aliases, and preserves the ROM binding and retained power helper's ownership.

The lifetime probe records helper addresses and checks the ROM binding during
each existing PHY guard. On S3 it also runs seven pure interpolation vectors
per guard. It issues no extra reset or channel-14 RF operation and does not
change calibration cadence or the AP channel. Host checks cover those branch
conditions; the live probe does not establish channel-14 RF behavior.
Traffic and remaining dependencies are recorded in the
[device comparison](PHY-BASIC-VALIDATION.md).
