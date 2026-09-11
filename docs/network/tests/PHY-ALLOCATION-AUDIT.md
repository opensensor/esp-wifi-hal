# Reproduce the PHY/printf allocation audit

The parser accepts the C3 LLD and S3 GNU ld maps used by these examples.
Install `pyelftools` in a local Python environment, then audit the ELF and map
from the **same link**:

```sh
python3 docs/network/tests/audit_phy_allocations.py \
  --elf "$ELF" --map "$MAP" --label combined-sta_smoke \
  --expect-printf source --expect-phy-wrappers source > allocation.json
```

Use `--expect-printf prebuilt --expect-phy-wrappers vendor` for the baseline,
and `--expect-printf source --expect-phy-wrappers vendor` for printf alone.
The gates also require no allocated `libpp.a` and retained PHY calibration,
tracking and parameter symbols. A failure must be investigated rather than
removing the corresponding gate from a comparison report.

For the source tracking dispatcher, also pass `--expect-phy-dispatcher source`.
It requires the original RAM body and its allocated input sections to be absent,
and the chip's temperature, power, PLL/calibration boundaries and callback table
to remain. The default `vendor` expectation preserves earlier audit behavior.

Each selected input range must fit wholly inside one ELF output section with
`SHF_ALLOC`. The parser discards the GNU discarded-input preamble and excludes
debug/nonallocated contributions, empty ranges, linker padding and symbols
that would duplicate input section sizes. It includes `COMMON` contributions,
which lack the leading period present on ordinary section names. Partial
overlap, duplicate ranges, overlapping counted inputs and unknown map formats
fail the audit. Code, literals, data and BSS all count; ROM contents do not.

GNU maps can report original, pre-merge string lengths which overlap other
inputs or extend beyond the final output section. The default audit rejects
these ranges. When this occurs, `--exclude-merged-strings` produces explicitly
**non-string** allocation totals. It extracts the named objects using `ar` and
requires `SHF_MERGE | SHF_STRINGS` on every excluded `.rodata*str*` section;
missing archives, unexpected flags and other overlaps still fail. The report
lists excluded map contributions separately. Their reported input lengths
cannot be added back as unique linked bytes because strings may be shared.
Use the same accounting mode for both sides of a comparison.

The report separates `libphy.a`, `libpp.a`, prebuilt `libprintf.a(printf.c.obj)`
and the source-built `*-printf.o`, either inside `libprintf.a` or bundled into
the patched chip's `esp-wifi-sys` rlib. Other `libprintf.a` members are reported
as `unknown_printf` and fail either printf expectation. Object classification
relies on the known build integration and must be paired with its source and
compiler provenance. A name alone cannot prove that arbitrary object bytes
came from the reviewed C source. Observed archive hashes describe files found
at audit time, which may differ from historical link inputs; unavailable
ephemeral archives receive a null hash. Preserve hashes during each build as
well. Unknown future packaging needs an explicit parser update.

JSON output contains image/map hashes, a caller-supplied simple artifact label,
sanitized archive member/section identifiers, address ranges, byte counts and
selected symbol addresses/sizes. It includes no filesystem paths, firmware
contents, calibration bytes, credentials or packet data. No device is accessed.
ELF and map hashes identify the audited pair; the tool cannot prove two
arbitrarily supplied files came from the same build.

Parser regressions use synthetic maps and need only the standard library:

```sh
python3 docs/network/tests/test_audit_phy_allocations.py
python3 -O docs/network/tests/test_audit_phy_allocations.py
```

The tests cover GNU discarded/debug exclusion, the allocated `COMMON` case,
LLD bundled-source attribution and symbol exclusion, GNU same-name printf
archive classification, partial/duplicate/overlap
rejection, unsupported map text, missing input-section names, and a mixed
prebuilt/source printf image rejected by the source-only expectation. They also
cover verified string exclusions, unverified exclusions rejected, and source
dispatcher absence/retained-helper gates.
