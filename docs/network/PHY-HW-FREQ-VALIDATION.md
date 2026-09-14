# C3/S3 hardware frequency replacement: paired validation

Rust now replaces all 11 functions per chip from `phy_hw_freq.o`. The tested
station images retain **six vendor PHY archive members**, down from seven.
The [implementation](PHY-HW-FREQ.md) preserves the original MMIO ordering,
I2C argument widths, frequency-memory construction, polling and channel retry
behavior. [Machine-readable evidence](phy-hw-freq-validation.json) records
hashes, build inputs, ownership checks, native traces and device results.

Implementation: `be4e11d6ffb44e2847b3eb3bdf2df58c61a2be8d`. Control: `3cc9637bf1cbdb593e5d828a468b51a74a40fb81`.
The allocation-auditor follow-up changes validation only. Both build sets use
the same passive lifetime probe and locked dependencies. FoA remains
`c433109960bc2b346a45da47c2bd3d2cb32690bf` and sys remains `73add8985cec3b7582e6df80a4273022deb844b0`.
The initial reconstruction used local Qwen3.8-flash-next and the closed-source
re-framework, followed by manual Rust work and independent checks. OpenSensor
Engineering is available for additional reverse-engineering and embedded
contract work.

## Software and ownership checks

- 1,418 C3 and 1,442 S3 original-instruction cases match production Rust at
  O0 and O2. All 927/1,039 recorded instructions, all 60/58 conditional edges
  and all 19 dispatch destinations per chip are reached. Another deterministic
  joint sweep exercises 704 cases per chip at both optimization levels.
- All eight compiled source profiles match the same traces: **11,440 native
  case executions** across the 88 emitted function bodies. The compiler's
  ten-entry I2C jump table is read from each ELF, bounded to its owner and
  byte checked. Compiler-generated panic paths are recognized as terminal;
  reaching them in a tested case would fail the comparison.
- Busy-wait, disable and enable helpers reside in IRAM, as do their literals.
  Their exercised external delay call resolves to the existing ROM entry.
- All 16 source/control firmware profiles build and pass the complete
  allocation gate. Earlier removed PHY members, `libpp.a` and the prebuilt
  formatter remain absent. There are 230 allocation regressions, run normally
  and under Python `-O`, plus 29 focused instruction-oracle tests. C/Rust HAL
  regressions and ESP32/S2 compatibility checks pass.

The initial allocation check correctly stopped at the old API validator's
assumption that `get_rf_freq_init` must remain a vendor body. Its explicit
hardware-frequency stage now checks the Rust body and alias while preserving
all other retained-helper checks. Native-checker bring-up added missing
instruction semantics, bounds-check exits and GNU-map readonly input parsing.
No firmware change was required by these checks.

| Chip / station profile | Control vendor PHY bytes | Source vendor PHY bytes | Removed member bytes |
| --- | ---: | ---: | ---: |
| esp32c3 / ordinary | 25242 | 22206 | 3036 → 0 |
| esp32c3 / GTK | 25242 | 22206 | 3036 → 0 |
| esp32s3 / ordinary | 24521 | 21419 | 3110 → 0 |
| esp32s3 / GTK | 24513 | 21411 | 3110 → 0 |

These are live, non-string input allocations in the tested linked images.
C3's retained wakeup call grows two bytes and `bb_init` shrinks two through
call encoding. S3 has a net eight-byte change across retained input sections;
resolved instructions match for the checked `bb_init`, TX calibration setup
and nine exported IRAM register functions. Member allocation changes and body
comparisons are recorded separately; source Rust and ROM are not counted as
vendor archive bytes. This does not establish archive-wide deblobbing.

## Board lifecycle and RX

All four lifetime trials complete three PHY enable/release cycles, preserving
the earlier temperature, PBUS, I2C, calibration and RF PLL probes. The new probe
passively observes all 11 frequency-control entries, five C3/six S3 callback
slots and initialization state. Addresses match the linked ELF and source
aliases; the first three entries are in IRAM. It adds no RF operation or poll.

| Chip | Variant | Lifecycle cycles | Beacons after wakeup | RX frames / OFDM |
| --- | --- | ---: | ---: | --- |
| esp32c3 | control | 3 | 2 | 9 / 2 |
| esp32c3 | source | 3 | 2 | 10 / 2 |
| esp32s3 | control | 3 | 2 | 10 / 2 |
| esp32s3 | source | 3 | 2 | 11 / 2 |

All four RX trials preserve pending buffers, recover from buffer exhaustion
and transmit OFDM.

## Station, rekey and packet observations

| Chip | Trial | Router echoes | Gateway echoes | Broadcast | Multicast | Rotations observed / requested |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| esp32c3 | control-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32c3 | source-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32c3 | control-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 3/3 |
| esp32c3 | source-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 3/3 |
| esp32c3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | control-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | source-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | control-gtk-v1 | 300/300 | 20/20 | 119/120 | 120/120 | 3/3 |
| esp32s3 | source-gtk-v1 | 299/300 | 20/20 | 120/120 | 120/120 | 3/3 |
| esp32s3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |

Across the ten station/restoration trials, **1439/1440 router echoes and
320/320 gateway echoes** arrive; **12/12 requested rotations**
are observed completed. All 18 planned device/restoration trials reach
completion on their first recorded attempt. Traffic losses remain recorded.

Missing router replies, verified against identifier, sequence and full payload in both AP captures:

- esp32s3 source-gtk-v1, sequence 139: request present in both captures; matching replies eth10/br0 = 0/0.

The missing S3 source echo is 2.216 seconds before the next GTK request and 7.750 seconds after the preceding G2. Neighboring echo requests 137/138/140/141 each have matching replies. That timing does not establish a rekey-induced stall or locate the loss.

All 12 accepted GTK requests appear at the AP, every captured G1 has a G2 reply, and no same-key retry is observed. C3 control/source and S3 source receive all broadcast and multicast packets. S3 control misses broadcast sequence 23, present in both AP captures 1.252 seconds after G2 counter 3.

The independent raw-pcap parser agrees with matched echo pairs, group
sequences, station-specific EAPOL ordering and completion of the captured
request intervals. The JSON retains per-request counters, retries, missing
frames and timing. Capture socket drops, truncations and missing kernel
timestamps are zero. AP Ethernet captures do not locate a loss within RF,
MAC, driver, stack or response transmission, and are not independent RF traces.

## Timing and restoration

| Chip / GTK variant | PHY maximum (us) | Console maximum (us) | TX resume maximum (us) | RX age maximum (us) |
| --- | ---: | ---: | ---: | ---: |
| esp32c3 / control-gtk-v1 | 88 | 1806 | 1648 | 8213 |
| esp32c3 / source-gtk-v1 | 84 | 1834 | 1415 | 8198 |
| esp32s3 / control-gtk-v1 | 96 | 3913 | 2578 | 8570 |
| esp32s3 / source-gtk-v1 | 91 | 3909 | 2448 | 11507 |

Cumulative maxima cannot associate a particular packet with a PHY operation.
One sequential trial per implementation and board does not establish a timing
improvement or regression. Packet loss and latency remain open.

Both boards retain ordinary source station applications after two additional
connection cycles each. Every flash checked explicit chip and security state;
S3 signatures were verified with the existing key. Only application slots were
written. Owned router workers/files were removed, monitor mode is zero, and
persistent AP configuration was unchanged. C3 ended disconnected; paired
flashing leaves S3 in ROM with its ordinary source application retained.

The six remaining members supply initialization, register programming, RX gain,
RX calibration, TX gain and TX calibration. Register programming (`phy_reg.o`)
is the next candidate. One board per chip, one AP and short room-temperature
trials do not establish calibrated RF accuracy, behavior at other temperatures,
sleep/coexistence correctness or long-duration reliability. The earlier
[RF PLL report and packet failures](PHY-RFPLL-VALIDATION.md) remain part of the
record.
