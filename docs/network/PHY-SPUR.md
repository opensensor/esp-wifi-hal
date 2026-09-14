# S3 RX spur configuration and power estimation

`spur_coef_cfg_new` and `phy_2448m_spur_pwr` now resolve to explicit Rust bodies
`__opensensor_spur_config` and `__opensensor_spur_power` on S3. C3 has no spur
transition. The composed ownership gate requires the entire S3 RX-calibration
archive member to disappear, including mergeable string inputs. TX calibration
and analog/ROM dependencies remain.

## Calling convention and sequencing

Configuration consumes seven machine arguments: six Xtensa argument registers
and the low byte at the caller's original stack pointer. Arguments 0/2/3/6
narrow to bytes, argument 1 to a signed byte and arguments 4/5 to halfwords.
Argument 0 sign-extends for the channel lookup and dynamic shift. The installed
S3 ROM `rom_spur_coef_cfg` uses the same seven-argument convention. Existing
source initialization installs this RAM replacement at callback slot `0x54`.

The first path depends on argument 2, parameter bytes `+0x2a6`/`+0x2d7` and
the strict threshold above ten. Argument 3 selects 40, 26, 24 or fallback 40;
the live parameter can select 48. Argument 1 selects scalar 10 or 20 at signed
threshold two. The second path depends on argument 4 and its channel/bit-14
mask. Scaling wraps the callback result before signed division by 100.
Disabled paths clear only bit 13 at `0x6001d014`/`0x6001d018`.

The final update reads `0x6001cc48` twice. The first snapshot selects the shift,
the second supplies the preserved upper byte. An explicit Xtensa `quos`
adapter preserves truncation toward zero, signed-overflow wrapping and the
zero-divisor exception; a compiler memory clobber keeps earlier observable
effects before that exception. No Rust panic or invented zero-divisor result
replaces the original behavior.

Power estimation takes a byte-valued logging argument. It selects channel 7,
sets frequency scalar 2443, enables a path through slot `0x40` with `(1,54)`
and starts a tone with `(1,128,0,0,0,0)`. Each of at most ten iterations reads
four MMIO words in the original order and preserves signed square/carry
arithmetic before numeric conversion through slot `0x104`. A second conversion
uses the signed power word shifted by nine. Rounded values use wrapped addition
and arithmetic shifts. Minimum selection is unsigned, and equal minima retain
the first associated value. Exit occurs at a minimum of 24 or less or after
ten attempts.

Tone/path cleanup precedes byte stores at parameter `+0x2d7`/`+0x2d8`. Logging
keeps the full selected words, original iteration index and wrapped elapsed
timer value. Existing PHY initialization invokes this routine with logging off.

| Callback slot | Scalars consumed | Result consumed |
|---|---:|---|
| `0x1d4` | 1 | full word, later a signed divisor |
| `0x50` | 4 | full word |
| `0x4c` | 2 | ignored |
| `0x40` | 2 | ignored |
| `0xf0` | 2 | ignored; estimator state changes |
| `0xf4` | 0 | ignored |
| `0x104` | 2 | full word |

The same channel-lookup slot is consumed by the earlier RF PLL reconstruction.
The estimator-enable slot is installed as source `ram_iq_est_enable`. Previous
power-detector validation observed numeric conversion slot `0x104` at S3 ROM
`0x40036794`. Those facts support the boundary ABI; they do not establish the
physical units or analog behavior of scripted callback results. Frequency,
channel, tone and printf helpers remain separately tested dependencies.

## Evidence and limits

The original executor and independent model agree on 4,308 deterministic cases,
covering all 237 original instructions and all 30 conditional edges. Seventeen
focused tests cover scalar narrowing, callback mutation, live reads, masks,
signed arithmetic, minima, termination and division. Production Rust matches
the original ordered traces at host O0/O2. The corpus includes 32 zero-divisor
exception boundaries, preserving prior effects without modeling exception-frame
construction or handler execution.

The caller supplies a valid initialized PHY table and parameter block. Synthetic
scalars and callback returns cover full words with the original entry narrowing.
The tests include callback-table and parameter changes between calls. Volatile
parameter/MMIO accesses retain their widths and order; private stack scheduling,
memory-barrier timing and asynchronous analog behavior are outside the model.

The [validation report](PHY-SPUR-VALIDATION.md) records all ten immutable builds,
four emitted S3 application profiles and ten device trials including restoration.
Both paired GTK trials completed all three rotations; the control lost one echo
and one broadcast packet, and the source trial received every measured packet.
Logging, FoA/sys pins and radio policy were fixed. This finite comparison does
not establish a packet-loss fix, timing equivalence or calibrated RF performance.

See [oracle and reproduction](tests/phy-spur-oracle/README.md).
