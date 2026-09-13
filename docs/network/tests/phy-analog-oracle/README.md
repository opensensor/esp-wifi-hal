# RC measurement/calibration instruction oracle

`original-instructions.json` records the reachable instructions of
`get_rc_dout` and `rc_cal`, their literal/data inputs, and named ROM boundaries
from the pinned pre-analog C3 and S3 station ELFs. `baselines.json` pins both
ELF and map hashes. The baseline includes the preceding power-detector
replacement. Baseline source revision: `31db517d890735d8a5f94efcf7365ee61cb9ccdd`.

Run from the repository root with Python 3 and stable Rust:

```sh
sh docs/network/tests/run-phy-analog.sh
```

The runner checks 25 focused interpreter regressions both normally and with
Python assertions disabled, generates each original-instruction stream, then
compares production Rust at O0 and O2. No firmware, hardware, credentials or
external model service is needed. Expected case counts and stream hashes are
pinned in `expected-results.json`.

| Chip | Measurement cases | Calibration cases | Total |
| --- | ---: | ---: | ---: |
| C3 | 68,740 | 267,624 | 336,364 |
| S3 | 68,740 | 136,552 | 205,292 |

The corpus covers all 16-bit selector and sample values on separate axes,
32-bit arithmetic edges, mode and completion flags, callback-table reloads,
state mutations, nested measurement calls, arbitrary raw callback returns,
and every signed low-halfword clamp result. C3 additionally sweeps every
16-bit value of each writable divisor independently, including zero. These
are selected axes and combinations, not the full Cartesian input domain.

The interpreter executes recorded RISC-V/Xtensa instructions. Code hashes,
instruction bytes, PC coverage, branch targets, supported operations, stack
reads, callback targets, and boundary access widths are checked. Callers'
volatile registers are poisoned. Modeled events include ordered parameter and
divisor reads, byte writes, fresh callback lookup and invocation, the 100-us
delay, and the exact low/high words at seven soft-double ROM calls. The
measurement result survives the two final cleanup writes. Calibration's void
return is normalized to zero.

ROM soft-double internals are opaque. Finite numeric cases use the host's
IEEE double arithmetic; separate overrides inject raw return words, including
non-numeric bit patterns, to check transport and call order. This tests the
wrapper contract and integer/narrowing behavior, not the ROM's numerical
implementation. Instruction/event budgets constrain the oracle only; they do
not add timeouts to production. The host mock and interpreter share an event
schema, so model mistakes remain possible. The native emitted-code comparison
and paired board runs are separate checks described in the validation report.

To reproduce a fixture from its exact private baseline, install pyelftools
and use the chip's GNU objdump:

```sh
python3 docs/network/tests/phy-analog-oracle/extract.py \
  esp32c3 /path/to/baseline.elf /path/to/baseline.map \
  /path/to/riscv32-esp-elf-objdump /tmp/c3-original.json
```

Use `esp32s3` and its Xtensa objdump for S3. The extractor reuses the bounded
code extractor in `../phy-pwdet-oracle/extract.py`. It takes data layout from
the pinned fixture, re-reads all recorded data and symbol addresses, and
requires the supplied ELF and map hashes. Both re-extracted structures were
compared with the checked-in fixture. No complete proprietary image or
network configuration is published.
