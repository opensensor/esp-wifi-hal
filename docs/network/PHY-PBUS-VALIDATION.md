# PBUS: C3/S3 source and device comparison

The [PBUS implementation](PHY-PBUS.md), commit `2b22fd9`, removes all allocated
`phy_pbus.o` inputs from both tested station images. The control is `e0ec914`,
which already has the earlier MAC, wrapper, dispatcher, temperature and complete
sensor-member replacements. Only PBUS implementation changes are compared here.
Both sides use the same expanded lifetime probe and pin FoA
`214311817b5234c1e9c911cd28a664cd392c366e`, with quiet timing logs, 80 MHz CPU and
the existing tracking cadence. The [numeric report](phy-pbus-validation.json)
records exact compiled source hashes, firmware hashes, allocation audits and
trial results. Source firmware was built before its implementation commit;
recorded source hashes are checked against that commit rather than treating the
build checkout's previous HEAD as the compiled source revision.

## Link and host evidence

| Chip | Control libphy bytes | Source libphy bytes | Original PBUS bytes | Source PBUS member bytes | PHY members |
| --- | ---: | ---: | ---: | ---: | --- |
| esp32c3 | 34,893 | 33,797 | 1,090 | 0 | 17 → 16 |
| esp32s3 | 32,575 | 31,603 | 972 | 0 | 17 → 16 |

These are allocated non-string vendor inputs, not total firmware savings. Source
functions and source constants also occupy space. C3 saves an additional six
vendor bytes because three existing calls in `phy_hw_freq.o` relax from JAL to
compressed C.JAL: `get_rf_freq_init` to `rfpll_set_freq`, and
`set_chan_freq_sw_start` to `correct_rfpll_offset` and `rom2_read_pll_cap`.
Their destinations move into compressed-jump range. S3 has no other vendor
input-size change. Its GTK builds are eight bytes smaller on both sides, with
the same 972-byte PBUS reduction.

All eight station/GTK allocation gates pass, including previous source
replacements and no allocated `libpp.a`. The lifetime and RX smoke profiles were
reviewed separately for selected aliases, native routing and member removal;
they are not mislabeled full station/tracking audits. `bb_init` calls the source
programmer under its original initialization flag. C3 installs the source force
callback; S3 retains its ROM force callback.

Production source matches **104,126 C3 and 98,840 S3 original-instruction cases**
at O0 and O2. All 26 focused oracle tests and 17 new allocation tests pass
normally and with Python assertions disabled; the full allocation suite has
66 tests. Previous HAL, dispatcher, temperature and sensor lifecycle suites
pass, as do ESP32/S2 cargo checks. The oracle covers every index byte, every
helper-return halfword with nonzero upper bits, wrapping pointer offsets,
changing callback tables/state, walking register bits, fresh reads and both
C3 force-mode branches. These are modeled boundary comparisons, not a proof
of analog behavior or cycle timing.

## Initialization, shutdown and reception

Both implementations on each chip pass three full PHY guard cycles with
nonempty calibration output, expected sensor state and shutdown flag, then
receive beacons after wakeup. The new read-only probe checks the initialization
flag and all six expected saved/live PBUS ranges on every cycle. C3's live force
callback matches its selected ELF entrypoint; S3's remains ROM `0x40035964`.
It does not manually invoke calibration transitions outside their original flow.

| Chip | Implementation | Temperature observations | Beacons after wakeup | RX-probe frames / OFDM |
| --- | --- | --- | ---: | --- |
| esp32c3 | control | 36 / 34 / 34 | 2 | 8 / 2 |
| esp32c3 | source | 32 / 30 / 30 | 2 | 9 / 2 |
| esp32s3 | control | 32 / 31 / 31 | 2 | 11 / 3 |
| esp32s3 | source | 33 / 32 / 32 | 2 | 8 / 2 |

All sensor observations used DAC 15/index 2. Runs were sequential, without
matched thermal conditions or an independent calibrated thermometer; these
values are not an accuracy comparison. `DataCheckFailed` describes the initially
empty input calibration buffer; nonempty output is checked separately. RX
pending-tail preservation, buffer exhaustion/recovery, OFDM transmission and
the existing channels 1–11 scan pass on both implementations.

## Traffic and GTK rotation

Each ordinary control/source trial completes two connections, with 40/40
router-originated and 40/40 gateway echoes. Each GTK trial uses one connection,
300 router echoes at five per second with 512-byte payloads, 20 gateway echoes,
120 broadcasts and 120 multicasts with 128-byte payloads, and three authenticated
station requests for group-key rotation. The router's persistent configuration
is unchanged.

| Chip | Implementation | Router echoes | Gateway echoes | Broadcast | Multicast | Median / maximum router RTT (ms) |
| --- | --- | --- | --- | --- | --- | --- |
| esp32c3 | control | 300/300 | 20/20 | 119/120 | 120/120 | 6.546 / 79.976 |
| esp32c3 | source | 300/300 | 20/20 | 120/120 | 120/120 | 4.505 / 80.855 |
| esp32s3 | control | 300/300 | 20/20 | 120/120 | 120/120 | 5.291 / 50.949 |
| esp32s3 | source | 300/300 | 20/20 | 120/120 | 120/120 | 4.950 / 91.201 |

All four trials complete three new GTK installations, with G1/G2 counters
3/4/5 and no retries or missing G2 in this comparison. S3 source takes
52.593 ms between the second G1 and its G2; no timing improvement is claimed.
AP captures are nonempty with zero reported socket drops,
truncation or missing kernel timestamps. Independent raw-capture review checks
payloads, sequence counts, selected EAPOL exchanges and captured reply pairs.
AP-originated EAPOL can appear only on the radio Ethernet interface; inbound
station message order agrees at both capture points.

Observed group gaps:

- esp32c3 control-gtk-v1: broadcast sequence 41 is absent at the station and present in both AP captures, 208.672 ms after completed G2 counter 4.

These observations do not establish a PBUS regression or a packet-loss fix.
The earlier reports' recovered missing-G2 events, group gaps and latency tails
remain part of the reliability record. Ethernet captures do not determine
whether a missing packet was lost on air, in hardware receive handling or in
software; they are not complete independent RF captures.

## Restoration and limits

Both boards are restored to ordinary source station firmware without the GTK
request probe. Each restoration completes two connections and 40/40 echoes in
both directions. Final application image hashes:

- esp32c3: `fd12c3969f528cac9fea208d5720bdc4189fa3e2be53209a29142e9eb131ab9a`
- esp32s3: `804bf73fbb0c5c18e5a6a76f28630b34482dc9a0e25418eae5c15f5f70bbdc0d`

Every flash checks both forced chip identities and security state. The existing
S3 signature is verified locally; only the existing application slots are
written. No key material, eFuse, bootloader or partition changes are involved.
Owned router workers and temporary tools are removed after testing, with
monitor mode confirmed off. Captures, serial logs, images and private network
configuration remain outside the public repository.

The remaining 16 PHY members and ROM callbacks still supply low-level bus
operations, RF initialization, channel/PLL control and RX/TX calibration.
This comparison uses one board per chip, one AP and room-temperature conditions.
It does not validate all channels/rates, coexistence, power saving, calibrated
RF properties or long-duration reliability. The next dependency work can build
on this bounded PBUS replacement while preserving the unresolved loss evidence.
