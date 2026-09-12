# S3/C3 WPA2 group-key rotation

The HAL examples pin FoA `214311817b5234c1e9c911cd28a664cd392c366e`, which adds
authenticated GTK updates while a station remains connected. The implementation
and replay-protection rules are documented in [FoA's report](https://github.com/opensensor/FoA/blob/214311817b5234c1e9c911cd28a664cd392c366e/GTK-REKEY.md).

The final 2026-09-12 repeats use the published pin and a 90-second connected
window per board:

| Chip | GTK rotations | Router echoes | Gateway echoes | Broadcast UDP | Multicast UDP |
| --- | ---: | ---: | ---: | ---: | ---: |
| S3 | 3 | 300/300 | 20/20 | 120/120 | 120/120 |
| C3 | 3 | 300/300 | 20/20 | 119/120 | 120/120 |

The final repeats verify one AP-captured test-station request, G1 and G2 for
each rotation, with matching replay counters.
Both old/new key IDs appear in authenticated group receive tracing. Validated
UDP payloads continue before, between and after the three key updates.

[`gtk-rekey-validation.json`](gtk-rekey-validation.json) includes the candidate
trials and fresh repeats built from the published FoA pin. It records image and
capture hashes, echo RTTs, per-window delivery counts, missing sequences, key
IDs, EAPOL counters and final capture statistics. Credentials, device identities,
raw captures and signing material are private.

This is a bounded WPA2-PSK/CCMP milestone. Earlier candidate trials received
118/120 S3 broadcasts and 120/120 C3 broadcasts; both received 120/120 multicasts.
The two missing candidate S3 broadcasts occurred after the third update, at
sequences 79 and 92. A further C3 repeat without valid AP capture received
118/120 broadcasts. Their cause, and the final C3 broadcast gap, remain
unresolved. A prior trial without an observed rotation also missed one broadcast.
These results do not establish indefinite reliability, lossless
broadcast reception, WPA3/PMF support or pairwise-key replacement support.
The older isolated echo losses remain open as well.

## Reproduce the mixed-traffic exercise

Use the existing ESP toolchain setup and supply `SSID`/`PASSWORD` privately.
From `examples`, build for the desired chip:

```sh
S3_SMOKE_CYCLES=1 STATION_TRAFFIC_SECONDS=90 \
TIMING_LOG_PROFILE=quiet TIMING_CPU_MHZ=80 \
cargo +esp build --locked --release --target xtensa-esp32s3-none-elf \
  --features esp32s3,neighbor-probe,gtk-rekey-probe --bin sta_smoke
```

For C3, select `riscv32imc-unknown-none-elf` and replace `esp32s3` with `esp32c3`
in the features. Load the application using the board's existing security-aware
workflow. Our secured S3 uses its existing signer and application slot; its
security configuration, bootloader and partition table were retained.

The probe sends three authenticated EAPOL-Key Requests, ten seconds apart.
**Each request can rotate the GTK for every station in the BSS.** The feature
is opt-in; ordinary builds never request rekeys automatically. The AP's
configuration and normal rekey interval are unchanged.

Run the [router traffic tools](tools/router-echo/README.md) concurrently after
`stage=traffic_ready`, capture EAPOL on the AP, and retain serial output through
`stage=complete`. A successful request transmit alone does not prove rotation:
require authenticated `gtk_update`, successful `gtk_reply`, matching AP G1/G2,
and valid traffic after the update. Group/echo counts must be reported exactly,
including missing or duplicate packets.

After capture, ordinary images built without `gtk-rekey-probe` passed two
reconnect cycles per chip: 40/40 router echoes and 40/40 gateway echoes each.
Those images remain in the application slots, so resets do not automatically
request another round of key rotations. No owned router capture workers remain.

## Failures retained during bring-up

The first requests used clear EAPOL after association. They were acknowledged
at the MAC but absent from the AP's EAPOL capture and did not establish rekeys.
Using the existing PTK made the request visible to hostapd. Its G1 then exposed
a reused pairwise envelope check that rejected group Key Length zero. That
trial ended with AP deauthentication reason 16 (group-key handshake timeout).
Its interrupted echo summary is incomplete and excluded from success counts.
The corrected parser retains the pairwise length-16 rule separately.

An audit found that the candidate C3 capture reused S3's remote stop-file name
and exited immediately. Its zero-packet captures cannot corroborate EAPOL;
the router and MCU traffic results are retained with that limitation. The
harness now uses fresh chip-specific stop files and requires nonempty captures
for the final independent checks. A C3 repeat using the same published image
supplies those captures.

A later repeat caught an M4 recovery regression: an AP that had not received
the initial M4 could not decrypt a protected M4 retry. The AP timed out the
initial handshake (reason 15), before DHCP or the traffic window. That trial
is also retained as a failure. FoA `2143118` keeps M4 retries clear even when
the station has installed its own PTK; only group messages use protected EAPOL.
The final repeats use this corrected published pin. Thirty host tests include
the production EAPOL serializer and inspect its actual radio submissions.

Host tests exercise production framing, installation and replay logic,
including invalid MICs, malformed lengths, repeated G1, old/new GTK IDs and
protected data. Hardware trials use natural exchanges; retry/reinstall cases
were not forced over the air. The radio's CCMP MIC checks remain a hardware
dependency.
