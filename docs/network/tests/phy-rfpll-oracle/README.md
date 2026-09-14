# RF PLL instruction oracle

The fixture records all 16 C3 and 18 S3 functions allocated from `phy_rfpll.o`
in the preceding tracking station images at source revision
`8f2f90d2a03f7fe1356b4d7ffa41618003759c57`. `baselines.json` pins the ELF and map
hashes. Instructions, literal words, named boundaries, two format strings,
C3's selector table and gain bytes are included. Complete firmware, keys and
network configuration are private.

From the repository root, with Python 3 and stable Rust:

```sh
sh docs/network/tests/run-phy-rfpll.sh
```

The runner executes 30 focused regressions normally and with Python assertions
disabled, then checks production Rust at O0 and O2 against 143,805 C3 and
145,305 S3 cases. Per-operation counts, fixture hashes, ordered stream hashes,
reached instructions and conditional edges are pinned in
`expected-results.json`. All 754 C3 / 707 S3 instructions and both edges of all
34 C3 / 32 S3 conditional branches are reached. Hardware-loop repetition is
interpreted separately.

| ID | Entry |
| --- | --- |
| 0 | `restart_cal` |
| 1 | `write_rfpll_sdm` |
| 2 | `wait_rfpll_cal_end` |
| 3 | `rfpll_set_freq` |
| 4 | `correct_rfpll_offset` |
| 5 | C3 `rom2_write_pll_cap`; S3 `ram_write_pll_cap` |
| 6 | C3 `rom2_read_pll_cap`; S3 `read_pll_cap` |
| 7 | C3 `ram2_rfpll_cap_correct`; S3 `rfpll_cap_correct` |
| 8 | `rfpll_cap_init_cal` |
| 9 | `set_rfpll_freq` |
| 10 | `set_rf_freq_offset` |
| 11 | `set_channel_rfpll_freq` |
| 12 | `chip_v7_set_chan_misc` |
| 13 | `chip_v7_set_chan` |
| 14 | `chip_v7_set_chan_offset` |
| 15 | `chip_v7_set_chan_ana` |
| 16 | S3 `phy_set_freq` |
| 17 | S3 `ram_pll_vol_cal` |

Only IDs 6/7/8/11/17 have scored return values. Incidental register values from
void functions are not API contracts. C3 arguments use a0–a7. S3 windowed calls
transport six arguments in registers and further arguments on the caller's
stack, including the sixth integer following the printf format.

The corpus exhausts each low-halfword value independently for frequency offset
and capacitor-write input. It also covers signed and word edges, all polling
completion positions through 100, calibration status transitions, early exits,
clamp and opaque returns, table replacement, parameter/buffer mutation, MMIO
read changes, nested helpers and selected pointer aliasing. This is not an
exhaustive combination of all these inputs. No model asserts RF behavior.

## Record format and boundaries

Each little-endian record is 48 case words, the normalized result, event count,
then 12 words per event. Event 1/2 is a memory read/write (canonical address,
width, value); 4/5 a table/slot read; 6 a callback with target and arguments;
7/8 MMIO; 9 an internal call; 10 an external helper; 12 printf; 13 a gain-buffer
snapshot. Events are zero-padded to 12 words. Table generations are represented
by distinct addresses. Parameter addresses start at `0x200000`, a frequency
buffer at `0x300000`, and a gain scratch buffer at `0x310000`.

| Case words | Meaning |
| --- | --- |
| 0–4 | operation and up to four arguments; selected pointer arguments are rebound |
| 5–6 | raw capacitor read returns |
| 7–9 | two clamp overrides and override enable |
| 10–13 | opaque initial cap, channel frequency, other opaque return, raw status noise |
| 14–16 | 32 two-bit status values and subsequent fallback |
| 17–18 | unsuccessful polls before a raw success return |
| 19–22 | repeating 32-call masks for table/state/buffer mutation and XOR seed |
| 23 | internal execution bitmask; S3 cap-write callback uses bit 5 |
| 24–29 | packed parameter fields, documented in `initial()` |
| 30–31 | buffer contents |
| 32–36 | four MMIO initial words and a per-read variation seed |
| 37 | external buffer, or a selected alias at parameter +0xe0/+0x11e |
| 38 | opaque frequency helper writes three buffer bytes |
| 39–47 | reserved; must be zero |

Outside-member helpers remain opaque and may mutate modeled state after every
call. Nested member execution can be enabled or suppressed. The ROM memcpy of
C3's nine local constant bytes is modeled as local scratch initialization,
checked against those exact bytes; it is not modeled as arbitrary mutable ROM.
Stack storage is otherwise checked for initialized reads, with caller-volatile
registers poisoned after calls. Pointer placement and stack layout are
canonicalized; internal scratch initialization does not generate a bus event.

The decoder verifies body hashes, instruction bytes, reachable PCs, branch
targets, supported operations, overlap and unrecorded padding. Execution is
bounded to 200,000 instructions, 4,096 events, 1,024 opaque calls and 12 call
levels per case. A boundary violation fails the test; it is not counted as
successful calibration. The production completion wait retains its actual
100-read bound. The shared mock/event schema can itself contain mistakes;
native emitted-code and hardware checks remain separate evidence.

## Re-extraction

With pyelftools and the target's GNU objdump:

```sh
python3 docs/network/tests/phy-rfpll-oracle/extract.py \
  esp32c3 /path/to/baseline.elf /path/to/baseline.map \
  /path/to/riscv32-esp-elf-objdump /tmp/c3-original.json
```

Use `esp32s3` and the Xtensa objdump for S3. Both input hashes are checked.
The bounded extractor reads code, literals, helper addresses, allocated input
bytes, strings and constants from the supplied ELF. Re-extraction of both
pinned baselines matched the checked-in structures exactly.
