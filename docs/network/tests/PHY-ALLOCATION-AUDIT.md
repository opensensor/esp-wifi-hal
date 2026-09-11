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

Each selected input range must fit wholly inside one ELF output section with
`SHF_ALLOC`. The parser discards the GNU discarded-input preamble and excludes
debug/nonallocated contributions, empty ranges, linker padding and symbols
that would duplicate input section sizes. It includes `COMMON` contributions,
which lack the leading period present on ordinary section names. Partial
overlap, duplicate ranges, overlapping counted inputs and unknown map formats
fail the audit. Code, literals, data and BSS all count; ROM contents do not.

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
prebuilt/source printf image rejected by the source-only expectation.
