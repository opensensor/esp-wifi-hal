# RX-IQ original-instruction oracle

The two fixtures per chip are `rxiq_get_mis` and `rxiq_cover_mg_mp`, extracted
from the preceding RX-control milestone's ordinary firmware. `baselines.json`
pins both ELF and map hashes; `extract.py` verifies the original code bytes,
reachable instructions, literals and diagnostic format. No live calibration
values or network configuration are included.

`machine.py` executes those original instructions. `verify.py` supplies explicit
boundaries for ROM signed 64-bit division, the previously replaced
`rxiq_set_reg`, analog estimator/disable callbacks and logging. Both halves of
the wide return are modeled; ordinary calls poison the unused high register.
The nested conversion executes its actual instruction body. Callback generations
and measurements can change after calls. Traces preserve access order, widths,
helper arguments/results, private output bytes, callback reloads and aliasing.

Run `../run-phy-rx-iq.sh`. The independent Rust runner invokes the production
implementation at optimization levels 0 and 2. Each chip has 2,182 cases,
covering every original PC and conditional edge: C3 218 instructions / 14 edges;
S3 181 / 12. Fourteen focused tests include evidence corruption, missing bodies,
signed low-16 multiplication, unsigned maximum, concatenated shifts, wide return
ABI, zero and negative denominators, logging narrowing, output aliasing, clamps
and changing callback tables. Python checks also run with `-O`.

The denominator comes from two signed 32-bit squares, summed with 64-bit wrapping.
Its only possible negative value is INT64_MIN; zero is replaced by one. Thus
INT64_MIN/-1 cannot be reached by this arithmetic. The helper model rejects that
case and division by zero instead of inventing ROM behavior.

Xtensa MUL16S/MUL16U, MAXU and SSL/SSR+SRC semantics are independently checked
against the matching [Espressif GCC machine patterns](https://github.com/espressif/gcc/blob/esp-14.2.0_20241119/gcc/config/xtensa/xtensa.md):
`<u>mulhisi3`, `any_minmax`, and `*shlrd`/rotate patterns. This is an inference
from compiler contracts. Focused tests include nonzero upper halfwords and
shift amounts 0 through 31. These extensions are isolated to this oracle;
previous milestone interpreters are unchanged.

This proves equivalence under the stated boundary models, not analog calibration
accuracy, full ROM behavior or packet-loss causality. Native emitted instructions
and device trials are recorded separately in the milestone validation report.
