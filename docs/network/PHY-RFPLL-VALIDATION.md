# RF PLL: C3/S3 source and device comparison

Implementation `683a5468474e07b40dd801fb9eb12797bdb3dde1` replaces every allocated input of
`phy_rfpll.o` with [Rust](PHY-RFPLL.md). Control `22bca2a7dbfc82725fea3d3423f59230edbffd47`
retains this member and all preceding source replacements. Both sides use the
same expanded lifetime probe, 80-MHz CPU and quiet timing logs. The
[numeric report](phy-rfpll-validation.json) records source/build hashes,
ownership, original/native instruction checks, captures and actual traffic.

FoA remains `c433109960bc2b346a45da47c2bd3d2cb32690bf`; sys remains
`73add8985cec3b7582e6df80a4273022deb844b0`. Sixteen builds use verified committed source/lock
content, with only the common lifetime-probe overlay on control. There are no
superseded firmware builds or rerun device trials in this comparison.

## Ownership and code checks

| Chip / station profile | Control vendor PHY bytes | Source vendor PHY bytes | RF PLL input removed | Members |
| --- | ---: | ---: | ---: | --- |
| esp32c3 / ordinary | 27,292 | 25,242 | 2,062 | 8 → 7 |
| esp32c3 / GTK | 27,292 | 25,242 | 2,062 | 8 → 7 |
| esp32s3 / ordinary | 26,393 | 24,521 | 1,876 | 8 → 7 |
| esp32s3 / GTK | 26,385 | 24,513 | 1,876 | 8 → 7 |

These are non-string vendor-input allocations, not whole-image savings; Rust
also occupies memory. C3 loses a 2,062-byte member but retained calls grow by
12 bytes: four compressed calls in `get_rf_freq_init` and two in
`set_chan_freq_sw_start` expand from two to four bytes. Every instruction and
branch destination agrees after resolving calls and parameter relocations.
S3 loses a 1,876-byte member while five retained literal pools change by a net
four bytes: `wr_rf_freq_mem` −8, `pll_cap_mem_update` −4,
`set_rx_gain_param` +8, `set_rx_gain_table` +4, `spur_coef_cfg_new` +4.
Those bodies retain their sizes and resolved instructions; referenced symbols,
strings and read-only data agree. Other retained inputs keep their identities
and sizes.

All 16 allocation audits pass the new gate and preceding source gates.
They reject RF PLL code, data, literals and excluded mergeable strings, check
all 16 C3 / 18 S3 source bodies and aliases, and retain absence of earlier
removed members, `libpp.a` and the prebuilt formatter. Alias sizes may be stale;
the real source body is checked separately.

Production passes **289,110 original-instruction cases at O0 and O2**:
143,805 C3 and 145,305 S3. All 754 C3 / 707 S3 recorded instructions and both
edges of every recorded conditional branch are reached. Thirty focused
interpreter tests and all 211 allocation regressions pass normally and under
Python -O. Both fixtures reproduce exactly from their pinned ELF/map inputs.
The HAL C/Rust regressions and ESP32/S2 compatibility checks pass; those two
older chips were not hardware-tested here. A separate deterministic joint
mutation sweep adds 2,048 C3 / 2,304 S3 cases at both optimization levels.

Native comparisons check four source profiles per chip, with 760 C3 and
854 S3 cases each: **6,456 case executions across 136 compiled entry bodies**.
They match ordered accesses, callbacks, direct calls, pointer contents and
register/stack arguments. The native checker was extended for emitted division,
shifted subtraction and stack-pointer movement instructions before the checks
passed. No source correction was needed after the first firmware builds.
These models are bounded comparisons, not full-domain, cycle-timing or RF
accuracy proofs. Wider helpers and analog behavior remain opaque boundaries.

## Lifetime and receive checks

All four lifetime trials complete three guard cycles, earlier probes,
calibration and shutdown. The new probe checks eight pinned pure frequency
vectors with two buffer canaries per cycle: 24 checks per trial. It observes
all new entry addresses and callback slots. Source addresses agree with their
strong aliases; S3's capacitor-write slot points to the new Rust entry.
Unresolved ROM callback addresses agree with control; this is not a validation
of those ROM bodies. No extra calibration or RF write is introduced by the
probe.

| Chip | Variant | Frequency vectors | Beacons after wakeup | RX frames / OFDM |
| --- | --- | ---: | ---: | --- |
| esp32c3 | control | 24 | 2 | 7 / 2 |
| esp32c3 | source | 24 | 2 | 11 / 2 |
| esp32s3 | control | 24 | 2 | 8 / 1 |
| esp32s3 | source | 24 | 2 | 9 / 2 |

All four RX trials preserve pending buffers, recover from buffer exhaustion
and transmit OFDM. Ordinary and restored station trials each complete two
connections, with all 40 router and 40 gateway echoes received in every trial.

## Key rotation and packet loss

| Chip | Variant | Router echoes | Gateway echoes | Broadcast | Multicast | Rotations observed / requested |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| esp32c3 | control | 300/300 | 20/20 | 119/120 | 120/120 | 3/3 |
| esp32c3 | source | 299/300 | 20/20 | 120/120 | 120/120 | 3/3 |
| esp32s3 | control | 299/300 | 20/20 | 120/120 | 120/120 | 2/3 |
| esp32s3 | source | 298/300 | 20/20 | 118/120 | 119/120 | 3/3 |

Across all ten station/restoration trials, **1436/1440 router echoes and
320/320 gateway echoes** arrive. All 18 planned device/restoration
trials reach completion on their first recorded attempt. Completion does not
mean loss-free traffic or that all requested key rotations reached the AP.
The initial sequencer stopped at C3 source's echo-worker exit 1; that completed
lossy trial was retained and skipped when the remaining planned trials resumed.

The missing router echoes are C3 source sequence 12, S3 control 184 and S3
source 144/264. Each request appears in both `eth10` and `br0` captures, with no
matching reply by identifier, sequence and full payload hash. C3 source's gap
precedes its first GTK request by 7.487 seconds. S3 control's gap is 26.814
seconds after its first request; S3 source's gaps are 18.744 and 42.745 seconds
after its first request. These observations do not locate the loss within RF,
MAC, driver, stack or response transmission.

The group gaps are:

- C3 control broadcast 21: present in both AP captures, 188.883 ms after G2
  counter 3 completes.
- S3 source broadcast 41 and 61: present in both captures, 93.845 and 92.509 ms
  after G2 counters 4 and 5 complete.
- S3 source multicast 106: present in both captures, 22.605 seconds after G2
  counter 5 completes.

C3 source's third requested rotation receives G1 counters 5, 6 and 7. The board
reports successful G2 transmission for each, but the AP captures only G2 7;
the interval completes after two retries. Counters 6/7 do not reinstall the
same key. S3 control accepts all three requests locally, but request counter 1
is absent from both AP captures. Its other two requests complete; that missing
request remains a failure. S3 source completes all three requested rotations.
Across the four runs, 11 of 12 requested rotations are observed completed.

The independent raw-pcap parser agrees with echo counts, group sequences,
station-specific EAPOL ordering and the completion of every captured request
interval. It retains the absent request and G1s without captured G2 replies.
There are no capture socket drops, truncations or missing kernel timestamps.
Ethernet captures are not independent RF captures. No retry-until-pass result
replaces any of these observations.

## Timing and restoration

| Chip / GTK variant | PHY maximum (us) | Console maximum (us) | TX resume maximum (us) | RX age maximum (us) |
| --- | ---: | ---: | ---: | ---: |
| esp32c3 / control-gtk-v1 | 86 | 1790 | 1322 | 8532 |
| esp32c3 / source-gtk-v1 | 86 | 1818 | 1625 | 8545 |
| esp32s3 / control-gtk-v1 | 88 | 4072 | 2466 | 8466 |
| esp32s3 / source-gtk-v1 | 102 | 4074 | 641 | 8789 |

These cumulative maxima cannot correlate a particular packet with a PHY
operation. The source/control difference in one short run cannot establish
improvement or regression. Packet loss and latency remain open; this milestone
removes an allocated blob member and does not claim to fix either.

Both boards retain ordinary source-v1 station images and complete two further
connections with every echo received. Every flash checked explicit chip and
security state; S3 application images used the existing signing key and had
their signatures verified. Only existing application slots were written.
Owned router workers/files were removed, monitor mode is zero, and persistent
AP configuration was unchanged. C3 ended disconnected; paired flashing leaves
S3 in ROM with its ordinary source application retained.

Seven allocated PHY members remain: hardware-frequency control, initialization,
register programming, RX gain, RX calibration, TX gain and TX calibration.
The next member is `phy_hw_freq.o`, which both calls and is called by the new
PLL source. One board per chip, one AP and short room-temperature trials do not
establish calibrated RF/power accuracy, other-temperature behavior,
sleep/coexistence correctness or long-duration reliability. Earlier
[tracking results and failures](PHY-TRACK-VALIDATION.md) remain part of the record.
