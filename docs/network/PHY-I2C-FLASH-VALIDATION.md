# Analog I2C flash setup: device comparison

The first stage of the [I2C replacement](PHY-I2C.md), commit `8d227ba`, replaces
four flash functions on C3 and S3. The control is `2d1a58a`, which includes the
previous MAC, PHY wrapper, dispatcher, temperature, sensor lifecycle and PBUS
replacements. The shared I2C IRAM section remains in both compared firmware
sets. The [numeric report](phy-i2c-flash-validation.json) records exact source
and firmware hashes, link audits and measured results.

Both sides pin FoA `214311817b5234c1e9c911cd28a664cd392c366e`, run at 80 MHz
with quiet timing logs and retain the existing tracking cadence. Firmware was
built before the implementation commit; compiled source hashes are checked
against that commit. The earlier build checkout HEAD is not treated as the
compiled source revision.

## Link and instruction evidence

| Chip | Control vendor PHY bytes | Source vendor PHY bytes | Original I2C bytes | Remaining I2C IRAM bytes | PHY members |
| --- | ---: | ---: | ---: | ---: | ---: |
| esp32c3 | 33,797 | 32,465 | 2,418 | 1,086 | 16 |
| esp32s3 | 31,603 | 30,588 | 1,985 | 970 | 16 |

These are allocated non-string vendor bytes, not total firmware savings. The
new Rust functions also occupy space. Both chips remove exactly the selected
flash inputs. S3 GTK builds have eight fewer vendor bytes on both sides, with
the same I2C reduction. All eight station/GTK allocation audits preserve every
previous source gate and no allocated `libpp.a`. Native review confirms that
`rf_init` calls all four new exports and the retained IRAM wakeup helper's
same-member call resolves to the new `phy_i2c_init2`.

Production code matches **167,348 C3 and 101,812 S3 original-instruction cases**
at O0 and O2. All 26 focused oracle tests and 20 new allocation tests pass
normally and with Python assertions disabled. The full allocation suite has
86 tests. Prior HAL, dispatcher, temperature, sensor lifecycle and PBUS suites
pass, along with ESP32/S2 compatibility checks. Tests cover callback-table and
parameter mutations, raw return words, arithmetic wrap, and chip-specific
parameter read and write ordering.

## Calibration and traffic

All eight control/source probe trials pass. Each lifetime trial completes three
PHY enable/release cycles, checks nonempty calibration output and sensor shutdown
state, verifies all six saved/live PBUS ranges, and receives beacons after wakeup.
RX probes preserve pending buffers, recover from exhaustion and transmit OFDM.
These use the original startup and wakeup flow, without manually invoking
calibration transitions.

| Chip | Trial | Router echoes | Gateway echoes | Broadcast | Multicast | Median / maximum router RTT (ms) |
| --- | --- | --- | --- | --- | --- | --- |
| esp32c3 | control-normal-v1 | 40/40 | 40/40 | — | — | 4.351 / 56.940 |
| esp32c3 | flash-normal-v1 | 40/40 | 40/40 | — | — | 4.027 / 30.426 |
| esp32c3 | control-gtk-v1 | 300/300 | 20/20 | 119/120 | 120/120 | 5.476 / 86.524 |
| esp32c3 | flash-gtk-v1 | 300/300 | 20/20 | 119/120 | 120/120 | 5.808 / 109.623 |
| esp32c3 | flash-restored-v1 | 40/40 | 40/40 | — | — | 4.838 / 34.416 |
| esp32s3 | control-normal-v1 | 40/40 | 40/40 | — | — | 2.583 / 57.430 |
| esp32s3 | flash-normal-v1 | 40/40 | 40/40 | — | — | 2.517 / 37.312 |
| esp32s3 | control-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 3.123 / 58.782 |
| esp32s3 | flash-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 4.878 / 222.905 |
| esp32s3 | flash-restored-v1 | 40/40 | 40/40 | — | — | 3.050 / 30.528 |
| esp32s3 | flash-gtk-repeat-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 3.288 / 76.137 |

Each ordinary and restored-firmware trial completes two connections. Each GTK
trial runs 300 router echoes with 512-byte payloads, 20 gateway echoes, 120
broadcasts and 120 multicasts with 128-byte payloads, and three attempts
to request authenticated group-key rotation. AP Ethernet and bridge captures are
nonempty with zero reported socket drops, truncation or missing kernel timestamps.
The independent reader verifies matching captured echo payloads and reviews
broadcast/multicast gaps and EAPOL messages.

- `esp32c3/control-gtk-v1`: missing group sequences `{'broadcast': [41], 'multicast': []}`; G1-to-G2 latency (ms) `{'3': 27.179, '4': 40.209, '5': 16.61}`.
- `esp32c3/flash-gtk-v1`: missing group sequences `{'broadcast': [21], 'multicast': []}`; G1-to-G2 latency (ms) `{'3': 11.605, '4': 38.481, '5': 61.018}`.
- `esp32s3/control-gtk-v1`: missing group sequences `{'broadcast': [], 'multicast': []}`; G1-to-G2 latency (ms) `{'3': 13.374, '4': 16.375, '5': 17.104}`.
- `esp32s3/flash-gtk-v1`: missing group sequences `{'broadcast': [], 'multicast': []}`; G1-to-G2 latency (ms) `{'3': 21.638, '4': 18.742}`.
- `esp32s3/flash-gtk-repeat-v1`: missing group sequences `{'broadcast': [], 'multicast': []}`; G1-to-G2 latency (ms) `{'3': 51.74, '4': 43.009, '5': 31.912}`.

The first S3 flash trial accepted three request API calls, but request counter
2 was absent from both AP captures and only two rotations completed. Ping and
group delivery continued. This failed exchange is retained alongside a repeat
of the same signed firmware; an accepted API call is not counted as proof of
an AP-observed exchange.

The numeric report retains each gap's presence and timing in both AP captures,
GTK installation/retry details and actual packet counts. This comparison does
not establish a packet-loss or timing fix. AP Ethernet captures do not locate
an RF loss or prove that an over-the-air retransmission occurred.

## Scope and restoration

Only existing application slots were written. S3 firmware was locally signed
and verified before flashing; forced chip identity and security-state checks
preceded every flash. No bootloader, partition table, eFuse or key was changed.
Ordinary first-stage source firmware was restored and tested on both boards.
Each trial's router capture and traffic workers were stopped afterward. The
owned temporary directory is reused for the following IRAM stage; monitor mode
and persistent router configuration are unchanged.

Results cover one board per chip, one AP and the tested room-temperature
conditions. There is no calibrated analog/RF measurement, long-duration or
instruction-cycle equivalence claim. ROM and remaining vendor PHY dependencies
continue to supply low-level transactions, calibration and channel control.
