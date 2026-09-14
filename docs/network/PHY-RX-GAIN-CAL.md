# Receive gain IQ/DC calibration

`set_rx_gain_cal_iq` and `set_rx_gain_cal_dc` now have Rust implementations for
C3 and S3. The linker retains explicit `__opensensor_rx_gain_cal_iq` and
`__opensensor_rx_gain_cal_dc` bodies with the original names as aliases.
Earlier source boundaries handle DC searches, IQ collection, tone control,
channel selection and channel sorting. Analog and ROM callbacks remain.

## Caller contract and chip differences

IQ calibration takes policy, frequency, two output halfwords and logging.
S3 narrows policy/logging to bytes and sign-extends the low frequency halfword;
C3 retains the machine scalar widths. Both recover signed five/six-bit TX IQ
fields from parameter offset `0x14c`, then search two gain settings. Each
setting gets at most four attempts. Coarse gain starts at indices 2/3 in
`[63,31,15,7,3,1,0]`, with fine gain 24. Power below 16,384 or above 131,072
adjusts gain; inclusive boundaries stop the search. A final adjustment on
exhaustion remains visible to logging and IQ collection, even though the
hardware gain callback last received the preceding setting.

The four-attempt state space proves that the unclamped fine value stays in
`-16..44`. The original C3 upper clamp at 120 cannot execute. The oracle checks
that complete bounded state enumeration and records exactly one original
instruction/edge exemption. Rust keeps the effective lower clamp. Native
coverage exemptions are not inferred from this original-code proof.

DC calibration consumes eight arguments on C3: policy, first stage, exclusive
end stage, gain codes, IQ words, DC words, channel words and code count. The
S3 caller supplies ten arguments: the first eight, middle-stage count and an
unused final argument. Its last four arrive on the caller stack; the routine
consumes only the first three of those. S3 narrows policy, stages and counts to
bytes. C3 retains initial machine widths and wraps the stage increment to a
byte, as the original does.

Stage zero writes count IQ words, starting at word zero for nonzero policy or
word nine otherwise. Stage one writes four DC words on C3; S3 uses the supplied
middle count and the five-entry table `[0,1,5,13,29]`. Stage two visits channels
2, 4, 6, 8, 10, 12 and 14. C3 calibrates three columns and duplicates each row
into its adjacent row; S3 calibrates one and duplicates each result into an
adjacent word. Status bytes follow the same layouts. A later stage retains
the original single-channel fallback. Both chips deliberately sign-extend the
low coefficient halfword before OR-packing the result; replacing that with an
unsigned halfword changes outputs.

The tested input domain uses first stages 0..2, exclusive end stages 0..4,
code counts 0..9, and S3 middle counts 0..5. Entering stage two requires at
least three codes on C3 or one on S3. Zero policy requires stage two to run,
because subsequent channel sorting consumes all 42 C3 / 14 S3 status bytes.
Callers supply sufficient aligned code/output buffers; IQ halfword outputs
need two-byte alignment, word arrays four-byte alignment. Caller buffers may
overlap each other. They must not overlap private stack, immutable tables or
the callback table. The original ABI is unsafe outside these bounds; the
replacement does not invent recovery behavior for invalid pointers/counts.

## Observable behavior and evidence

MMIO and parameter/caller reads and writes retain their widths and order.
Callback targets reload from the live table between calls. Tests change that
table and mutate externally visible inputs during callbacks. Helper buffers
are checked at their boundaries, including coefficients carried between
iterations, signed packed outputs and complete sort status inputs. Private
stack spill/load scheduling and fixed readonly table copies are excluded.
The original S3 ROM `memcpy` calls copy pinned 7-, 5- and 10-byte tables;
Rust initializes equivalent private constants without that ROM call.

Run `sh docs/network/tests/run-phy-rx-gain-cal.sh`. The original instruction
executor and independent model agree on 1,395 C3 and 1,516 S3 cases. Production
Rust is tested against the original traces at O0/O2. Seventeen focused oracle
tests check signatures, scalar narrowing, aliases, signed packing, zero counts,
callback caching, invalid domains and the upper-clamp proof. Thirteen new
allocation tests require explicit transitions through the earlier ownership
gates, preserve the S3 spur helpers and reject any remaining C3 RX member,
including mergeable string inputs.

The 570 C3 instructions have 569 executed instructions and 59/60 conditional
edges, with only the documented upper-clamp exemption. All 520 S3 instructions
and 54 conditional edges execute. These finite software cases do not establish
analog/RF behavior, cycle counts or packet-loss equivalence. The
[validation report](PHY-RX-GAIN-CAL-VALIDATION.md) records all eight emitted
profiles and eighteen device trials, including restoration and retained losses.
Network logging, FoA/sys revisions and radio policy stayed fixed for the PHY
comparison.

The subsequent [S3 spur milestone](PHY-SPUR-VALIDATION.md) removes the two
remaining S3 RX bodies. Its composed gate explicitly enables that transition
and requires the entire RX archive member, including strings, to disappear.
The gain-calibration gate still preserves spur ownership by default for earlier
profiles. Both chips retain TX calibration and analog/ROM dependencies.
