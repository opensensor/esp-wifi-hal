# Complete I2C member: C3/S3 source and device comparison

The [Rust I2C implementation](PHY-I2C.md), commit `561a000`, removes every
allocated `phy_i2c.o` input on both tested chips. This completes the
[flash-stage replacement](PHY-I2C-FLASH-VALIDATION.md). The control remains
`2d1a58a`, with the earlier MAC and PHY replacements and original I2C member.
Both implementations use the same expanded, read-only lifetime probe.
The [numeric report](phy-i2c-validation.json) records source and firmware
hashes, allocation gates, callback observations and actual traffic counts.

FoA stays pinned to `214311817b5234c1e9c911cd28a664cd392c366e` and sys to
`73add8985cec3b7582e6df80a4273022deb844b0`. Both sides use an 80 MHz CPU,
quiet timing logs and unchanged tracking cadence. Firmware was built before
its implementation commit; relevant compiled source hashes are checked
against that commit, rather than assuming the build checkout HEAD identifies
the modified source. Original vendor archives are unchanged.

## Link and instruction evidence

| Chip | Control vendor PHY bytes | Source vendor PHY bytes | Original I2C bytes | Remaining I2C bytes | PHY members |
| --- | ---: | ---: | ---: | ---: | --- |
| esp32c3 | 33,797 | 31,377 | 2,418 | 0 | 16 → 15 |
| esp32s3 | 31,603 | 29,618 | 1,985 | 0 | 16 → 15 |

These are allocated non-string vendor inputs, not total firmware savings.
Rust functions and data also occupy space. C3's extra two-byte reduction is
an existing wakeup call in `phy_init.o` relaxing from JAL to C.JAL after its
destination moves into range. No other retained C3 input changes size. S3
removes exactly 1,985 I2C bytes; GTK builds are eight bytes smaller on both
sides. All eight station/GTK gates preserve previous source replacements,
absent sensor/PBUS members and no allocated `libpp.a`.

All eight selected low-level exports per chip are in IRAM. The four fixed
block/register arrays are a 40-byte DRAM object with SHA-256
`80bff8b7d758d09011f9945d97a5b89c7cd28e064b1afd79ee46cf74b50c3df0`.
An independent review decoded those arrays from original init1 instructions
and compared them with both actual ELF objects. The native first initializer
uses ROM `memset` on C3 and no memory helper on S3; reviewed S3 literals are
in IRAM. The batch callback receives six ten-byte stack arrays plus length
ten and flag zero, including the S3 stack-passed final arguments.

Read/write host selection, raw pause tokens and callback reloads retain their
original behavior. S3 forwards the raw returned host word before the retained
ROM callee narrows it; actual installed host IDs are zero or one. Source
critical entries retain the original no-op behavior, and writes retain the
original unbounded busy-bit polling. Wakeup's conditional call into flash
already exists in the original; this is not a claim that every transitive
path can execute with flash inaccessible. C3 keeps its ROM TXCAP binding;
the unused 142-byte original body disappears with the shared IRAM input.

Production matches **509,928 original-instruction cases at O0 and O2**:
167,348/101,812 C3/S3 flash cases plus 104,768/136,000 IRAM cases. All 56
focused oracle tests and 24 I2C allocation tests pass normally and with
Python assertions disabled; the full allocation suite has 90 tests.
The preceding HAL and PHY suites and ESP32/S2 compatibility checks pass.
Host traces cover dynamic batch arrays; actual native bytes separately check
the four fixed arrays and no-op critical exports. These comparisons do not
establish cycle timing, analog/RF equivalence or safe arbitrary MMIO inputs.

## Calibration, callback installation and reception

Both control and source on each board pass three normal PHY guard cycles,
nonempty calibration output, sensor state/shutdown checks and all six PBUS
ranges, then receive beacons after wakeup. The expanded probe reads the live
I2C callback table after each normal initialization and compares it against
the selected ELF entrypoints. It observes four slots per C3 cycle and five
per S3 cycle, including S3 TXCAP. Source observations match the Rust aliases.
The probe does not write the table or issue extra analog transactions.

| Chip | Implementation | Live I2C slot checks | Beacons after wakeup | RX frames / OFDM |
| --- | --- | ---: | ---: | --- |
| esp32c3 | control | 12 | 2 | 8 / 2 |
| esp32c3 | source | 12 | 2 | 11 / 2 |
| esp32s3 | control | 15 | 2 | 8 / 2 |
| esp32s3 | source | 15 | 2 | 9 / 2 |

All four RX probes preserve pending buffers, recover from exhaustion and
transmit OFDM. The reduced lifetime/RX link profiles receive separate alias,
member and DRAM-table reviews, rather than being described as full station
audits. Temperature observations are recorded numerically; sequential runs
without controlled thermal conditions are not an accuracy comparison.

## Traffic and key rotation

Every ordinary control/source and restored-source trial uses two connections.
GTK trials use one connection, 300 router echoes with 512-byte payloads,
20 gateway echoes, 120 broadcasts and 120 multicasts with 128-byte payloads,
and three attempts to request authenticated group-key rotation.

| Chip | Trial | Router echoes | Gateway echoes | Broadcast | Multicast | Median / maximum router RTT (ms) |
| --- | --- | --- | --- | --- | --- | --- |
| esp32c3 | control-normal-v2 | 40/40 | 40/40 | — | — | 5.112 / 24.784 |
| esp32c3 | source-normal-v2 | 40/40 | 40/40 | — | — | 5.870 / 24.006 |
| esp32c3 | control-gtk-v2 | 300/300 | 20/20 | 120/120 | 120/120 | 5.753 / 96.026 |
| esp32c3 | source-gtk-v2 | 300/300 | 20/20 | 120/120 | 120/120 | 5.822 / 77.581 |
| esp32c3 | source-restored-v2 | 40/40 | 40/40 | — | — | 3.936 / 54.709 |
| esp32s3 | control-normal-v2 | 40/40 | 40/40 | — | — | 2.418 / 24.582 |
| esp32s3 | source-normal-v2 | 40/40 | 40/40 | — | — | 3.700 / 73.017 |
| esp32s3 | control-gtk-v2 | 300/300 | 20/20 | 120/120 | 120/120 | 3.098 / 51.720 |
| esp32s3 | source-gtk-v2 | 300/300 | 20/20 | 120/120 | 120/120 | 3.127 / 48.957 |
| esp32s3 | source-restored-v2 | 40/40 | 40/40 | — | — | 2.689 / 32.817 |

AP Ethernet and bridge captures are nonempty, with zero reported drops,
truncation and missing kernel timestamps. Independent capture review checks
matching echo identifiers, sequence numbers and full payload hashes, then
compares group gaps and EAPOL requests/replies with the device logs.

- `esp32c3/control-gtk-v2`: 3 rotations; missing AP request counters `[]`; missing group sequences `{'broadcast': [], 'multicast': []}`; G1-to-G2 latency (ms) `{'3': 23.069, '4': 22.04, '5': 16.122}`.
- `esp32c3/source-gtk-v2`: 3 rotations; missing AP request counters `[]`; missing group sequences `{'broadcast': [], 'multicast': []}`; G1-to-G2 latency (ms) `{'3': 38.629, '4': 15.829, '5': 19.245}`.
- `esp32s3/control-gtk-v2`: 3 rotations; missing AP request counters `[]`; missing group sequences `{'broadcast': [], 'multicast': []}`; G1-to-G2 latency (ms) `{'3': 31.454, '4': 16.272, '5': 13.886}`.
- `esp32s3/source-gtk-v2`: 3 rotations; missing AP request counters `[]`; missing group sequences `{'broadcast': [], 'multicast': []}`; G1-to-G2 latency (ms) `{'3': 22.006, '4': 18.113, '5': 14.366}`.

The earlier flash-only comparison's broadcast gaps and missing S3 request
remain part of the evidence. A repeat of that same signed firmware completed
the missing exchange. Neither a successful repeat nor this whole-member
comparison establishes a packet-loss or timing fix. Ethernet captures cannot
locate an RF loss or prove over-the-air retransmission behavior.

Review also found a separate defect in pinned FoA: the common EAPOL sender
returns success when `wait_for_completion` returns `None`, which means no
completion is available. That result is distinct from a reported ACK failure.
It could arise from overwritten completion state or an aborted transmitter.
The first missing S3 request lacks the completion diagnostic needed to prove
it took this path. The FoA pin is unchanged for these I2C comparisons; a follow-up
should report missing completion explicitly and test the actual sender's three
outcomes before investigating retry policy.

## Restoration and limits

Both boards were restored to ordinary complete-source station images and
passed two more connections with the packet counts above. Every flash was
preceded by forced chip identity and security-state checks. S3 images were
locally signed and verified. Only existing application slots were written;
bootloader, partition tables, eFuses and keys are unchanged. Owned router
workers were stopped and the milestone's temporary directory removed, with
monitor mode verified zero and persistent router configuration unchanged.

This is one board per chip, one AP and the tested room-temperature conditions.
There is no calibrated RF measurement, long-duration reliability or analog
compliance claim. ROM pause/resume, low-level batch/read and calibration helpers
remain, along with other vendor PHY members, state, RF/channel initialization
and RX/TX calibration. Removing this member does not remove the whole PHY.
