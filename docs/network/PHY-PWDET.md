# C3/S3 power-detector member replacement

`esp-wifi-hal/src/phy_pwdet.rs` replaces every allocated `phy_pwdet.o` input
in the compared C3/S3 images. Strong aliases select nine C3 and eight S3
source entries. The original archives, ROM ADC/conversion callbacks, PHY
state and calibration policy remain dependencies.

## Reference arithmetic and sample buffers

`get_sar_sig_ref` reads the unsigned halfwords at `phy_param+0xda` and
`phy_param+0xdc` before either output store. It adds 40 on C3 or 50 on S3 to
the input, narrows to 16 bits, then computes unsigned comparisons followed
by low-16-bit differences. The signal and reference outputs are written in
that order. Output aliasing, including overlap with the parameter fields,
retains both original reads and the ordered stores.

`rom1_read_sar2_code` (C3) and `ram_read_sar2_code` (S3) reload the callback
table separately for setup and output collection. The output callback writes
**eight halfwords, or sixteen bytes**, although these wrappers return only
the unsigned halfword at offset two. The source allocates a sixteen-byte
buffer with sixteen-byte alignment and reads the second sample after the
callback. It does not initialize or read the other samples prematurely.

The installed ROM bodies and observed control-probe targets establish the
buffer boundary. [ROM evidence](tests/phy-pwdet-oracle/rom-buffer-boundary.json)
records body bytes, hashes and instructions without bundling a ROM image.
C3 rev0/rev3/rev101 bodies are byte-identical at different addresses; the
connected C3 selects the rev3 address. S3 selects its recorded rev0 body.
Both bodies read eight words from `0x6000e080` through `0x6000e09c`, mask each
to thirteen bits, and write consecutive halfwords. A callback replacement
must continue to satisfy this write contract.

| Boundary | C3 slot / observed target | S3 slot / observed target |
| --- | --- | --- |
| Setup | `0x144` / selected `ram_pkdet_vol_start` | `0x120` / ROM `0x40036a18` |
| Fill sixteen-byte output | `0x148` / ROM `0x4003a2cc` | `0x124` / ROM `0x40036aa4` |
| Wrapper installed in table | `0x14c` / selected `rom1_read_sar2_code` | `0x128` / selected `ram_read_sar2_code` |
| Convert signed sample | `0x118` / ROM `0x40039ff2` | `0x104` / ROM `0x40036794` |

The C3 setup entry and both wrappers move to source with this replacement.
The remaining numeric targets stay in ROM. Every indirect call reloads the
table and slot; the conversion boundary takes a sign-extended sample and
selector three, preserving the raw 32-bit return across the second call.

## Sequencing and arithmetic

`pwdet_tone_start` sets bit 18 at `0x60006040`, delays one microsecond,
clears then sets bit one at `0x6000e050`, delays two microseconds, polls
bits 24–26 until they equal seven, and clears the first bit. C3 additionally
supplies `ram_pkdet_vol_start`: set bits 21 and 19 at `0x6000e05c` in separate
writes, poll readiness, clear/set bit one at `0x6000e050`, delay ten
microseconds, poll again, and clear bits 21 and 19 separately. Each operation
preserves its own read-modify-write; the source introduces no timeout.

`get_tone_sar_dout` calls the tone helper and output callback for each sample,
accumulates unsigned halfwords with 32-bit wrapping, divides by its eight-bit
counter, and returns the low halfword. S3 narrows the requested count to a
byte; C3 compares the counter to the full request. Normal callers use counts
in 1–255. A C3 count above 255 cannot match the wrapping counter. Zero count
produces `0xffff` on C3; S3 raises the native integer-divide exception, also
for a request that narrows to zero. This follows [RISC-V unsigned division,
section 13.2](https://docs.riscv.org/reference/isa/v20240411/_attachments/riscv-unprivileged.pdf)
and [Xtensa QUOU](https://www.cadence.com/content/dam/cadence-www/global/en_US/documents/tools/silicon-solutions/compute-ip/isa-summary.pdf#page=558).
S3 uses one inline QUOU instruction and its existing Xtensa toolchain's
`asm_experimental_arch` feature to preserve that exception behavior.

`get_fm_sar_dout` obtains two samples, writes the two reference outputs and
returns zero. `txtone_linear_pwr` performs that sampling/reference sequence
twice, replaces a zero local denominator with one, divides the signed
signal shifted left ten by the signed reference, and accumulates modulo
16 bits. `get_power_db` obtains the reference pair, converts each signed
halfword with selector three, adds the first raw return to the caller's
offset, subtracts the second, and returns signed16. S3 narrows the caller's
offset to 16 bits first. `phy_set_pwdet_power` remains the observed no-op.

## Validation boundaries

The [instruction oracle](tests/phy-pwdet-oracle/README.md) compares production
Rust with 913,536 cases at O0 and O2. It covers reads/stores and aliases,
callback mutations, nested and opaque helper boundaries, full sample writes,
polling schedules, counter wrapping and signed arithmetic. Exceptions and
bounded non-completing prefixes are distinct from successful returns.
Twenty-one focused oracle regressions and 171 allocation regressions run
normally and with Python assertions disabled.

```sh
sh docs/network/tests/run-phy-pwdet.sh
python3 docs/network/tests/test_audit_phy_pwdet.py
python3 -O docs/network/tests/test_audit_phy_pwdet.py
python3 docs/network/tests/audit_phy_pwdet.py \
  --elf /path/source-sta_smoke.elf --map /path/source-sta_smoke.map \
  --label source --expect-pwdet source
```

Native review covers 68 source bodies across four profiles per chip. All
entries remain in flash. The review checks aliases, direct and indirect call
boundaries, sixteen-byte buffer extent/alignment and separation from explicit
stack spills. The linear helper contains a compiler-generated divide-by-zero
panic branch; its local denominator is made nonzero before division under
the verified output contract. Its shifted signed16 numerator cannot overflow
signed32 division. Instruction counts, stack frames and barriers differ from
the original, so this is not cycle or analog equivalence.

The common lifetime probe checks ten pure reference vectors per cycle with
destination guard halfwords and records selected entries and callback targets.
It adds no tone generation, ADC collection or parameter writes. Ordinary
calibration, lifecycle, RX and station traffic exercise the normal driver
workload. Unusual counts or stalled hardware are modeled on the host rather
than deliberately triggered on the boards. Device evidence is recorded in
[the validation report](PHY-PWDET-VALIDATION.md).
