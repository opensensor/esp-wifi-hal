# PHY tracking instruction oracle

The fixture contains the reachable instructions for all seven C3 and eight
S3 functions allocated from `phy_track.o`. It was extracted from the preceding
analog-calibration station ELFs at source revision
`2dca8f3e0e8e781d25894739bb9d6b0d29799db9`. ELF and map hashes are pinned in
`baselines.json`. It includes literal words, named external boundaries and
exact debug format strings. No complete firmware image or network configuration
is included.

From the repository root, with Python 3 and stable Rust:

```sh
sh docs/network/tests/run-phy-track.sh
```

The runner checks 30 focused oracle regressions normally and with Python
assertions disabled, then compares the production Rust at O0 and O2 against
238,658 C3 and 244,580 S3 instruction-driven cases. Case counts, per-operation
coverage and stream hashes are pinned in `expected-results.json`.

| Operation | C3 name | S3 name |
| --- | --- | --- |
| 0 | `rom2_wait_hw_freq_busy` | `wait_hw_freq_busy` |
| 1 | `rom2_ulp_ext_code_set` | `ulp_ext_code_set` |
| 2 | `rom2_ulp_code_track` | `ulp_code_track` |
| 3 | `ram2_rfpll_cap_track` | `rfpll_cap_track` |
| 4 | `rom1_txpwr_cal_track` | `ram_txpwr_cal_track` |
| 5 | `txpwr_offset` | `txpwr_offset` |
| 6 | `rfcal_track` | — |
| 7 | — | `ram_wifi_track_tx_power` |
| 8 | — | `ram_bt_track_tx_power` |

The corpus sweeps every low-halfword value independently for ULP signed delta,
ULP clamp return and power clamp return, plus byte arguments with nonzero upper
bits, thresholds, mode branches, signed arithmetic, arbitrary 32-bit helper
returns, state mutations after opaque calls, callback-table replacement,
optional logging, and nested tracking helpers. This covers selected axes and
combinations, not the full Cartesian input domain.

Ordered events include parameter reads/writes and widths, separate table and
slot reads, callback invocation arguments, direct external calls, debug-print
arguments and the frequency-busy register. Internal ROM/calibration behavior
stays opaque. Caller-volatile registers are poisoned. Void returns are not
scored as values. For the busy loop, immediate idle produces no delay; observing
busy and then idle produces one 50-us delay. Two cases per chip stop the model
after 64 busy reads and compare that prefix; they do not claim completion or
introduce a timeout into production.

The decoder checks code hashes, instruction bytes, PC coverage, branch targets,
supported operations and unrecorded padding. Execution checks stack accesses,
parameter widths, callback targets and budgets. The host mock and interpreter
share an event schema, so model mistakes remain possible. Native emitted-code
checks and paired hardware trials are separate evidence; these tests do not
establish cycle timing, RF accuracy or long-duration reliability.

To reproduce a fixture from its exact baseline, install pyelftools and use the
chip's GNU objdump:

```sh
python3 docs/network/tests/phy-track-oracle/extract.py \
  esp32c3 /path/to/baseline.elf /path/to/baseline.map \
  /path/to/riscv32-esp-elf-objdump /tmp/c3-original.json
```

Use `esp32s3` and its Xtensa objdump for S3. The extractor reuses the bounded
extractor in `../phy-pwdet-oracle/extract.py`; it reads instruction bytes,
literals, symbol addresses and format strings from the supplied ELF and checks
both input hashes. Both extracted structures were compared exactly with the
checked-in fixture.
