# WPA2 message-4 loss recovery

The quiet timing investigation found a separate protocol defect: after its initial
four-way handshake returned, FoA discarded retransmitted message 3 frames. If the
AP missed message 4, the station reported link-up but never answered those retries.
The AP could then deauthenticate with reason 15, presenting as a DHCP timeout.

The examples now pin FoA `bf89a5661682572416e5de3ce5f83ced86e571b4`.
Its background handler authenticates M3 retries for the installed exchange and
resends M4. It verifies framing, addresses/direction, MIC, nonce, increasing EAPOL
replay counter and unchanged GTK/key ID. It does not reinstall keys or reset CCMP
packet numbers. The [implementation and host tests](https://github.com/opensensor/FoA/blob/bf89a5661682572416e5de3ce5f83ced86e571b4/tests/EAPOL-RETRANSMIT.md)
describe the validation boundary. Message-1 retry recovery, GTK rekeying and new
pairwise exchanges remain separate work.

Codex assisted the source investigation, Rust implementation and test work.
The evidence below comes from host regressions and the attached C3/S3 boards.

## Controlled reproduction

A private test patch suppressed the first outgoing M4 once, returning local
success. It changed neither the AP nor incoming traffic. The baseline S3 then
recorded M3 headers (`0x13ca`) at approximately 2.165, 3.165 and 4.167 seconds
relative to connection start, after declaring local completion at 1.168 seconds.
All three entered the background queue. Reason-15 deauthentication followed and
DHCP timed out. With the recovery handler and the same omission, the S3 completed
DHCP and both twenty-ping tests. That run received three EAPOL frames total: the
initial M1/M3 plus an additional M3.

| Chip / experiment | Traffic cycles | Host replies | Gateway replies | Outcome |
| --- | ---: | ---: | ---: | --- |
| S3 initial phase recorder | 8 | 160/160 | 160/160 | Cycle 9 DHCP timeout after local handshake completion and reason-15 deauth |
| C3 initial phase recorder | 10 | 200/200 | 200/200 | Complete |
| S3 extended recorder | 10 | 200/200 | 200/200 | Complete |
| S3 suppress first M4, baseline | 0 | — | — | Three ignored M3 retries; DHCP timeout |
| S3 suppress first M4, recovery | 1 | 20/20 | 20/20 | Complete |
| C3 recovery, normal traffic | 10 | 200/200 | 200/200 | Complete |
| S3 published FoA pin, normal traffic | 10 | 200/200 | 200/200 | Complete |

The suppression hook was private test instrumentation and is absent from the
published code. The failed baseline is retained alongside the successful control.
This experiment establishes recovery from one lost M4. It does not prove that the
earlier natural timeout had the same initiating cause: its original recorder
stopped at local completion and did not retain the subsequent EAPOL exchange.
Nor does the experiment establish why a particular MAC completion might report
success without AP acceptance.

All runs use one active station, quiet logging, 80-MHz CPU, the same AP and the
existing PHY tracking cadence, queue sizes and connection/DHCP deadlines. Traffic
tests send twenty 512-byte host and twenty gateway echoes per cycle, counting the
first ping without an ARP warmup. Captures contain Ethernet ARP/ICMP metadata for
the traffic check; they do not capture the wireless EAPOL exchange. The in-memory
station recorder supplies handshake evidence. All completed captures in the
[numeric evidence](eapol-retransmit-validation.json) report zero socket drops.

## Timing measurements

The initial phase recorder measured 1,128,525–1,128,543 us of synchronous PMK
derivation per S3 reconnect and approximately 936,000 us on C3 at 80 MHz. It occurs
before authentication is transmitted. This is a concrete setup cost and explains
why radio-servicing age can include a second-long interval during connection
bringup; it does not establish a one-second WPA message-processing delay.
Successful initial S3 four-way exchanges generally took about 17–31 ms from M1
wait through local M4 completion. These are software phase intervals, not on-air
ACK/SIFS timings.

The [console timing correction](RUST-TIMING.md) remains in place. This change does
not alter CPU defaults, PHY cadence or timeouts. PMK caching and remaining
handshake cases need their own measurements and validation.

## Reproduce and inspect

From `examples`, with private `SSID` and `PASSWORD` build variables and the chip
toolchain configured:

```sh
TIMING_LOG_PROFILE=quiet TIMING_CPU_MHZ=80 S3_SMOKE_CYCLES=10 \
  cargo +esp build --locked --release --target xtensa-esp32s3-none-elf \
  --features esp32s3,handshake-probe --bin sta_smoke
```

For C3 select `riscv32imc-unknown-none-elf` and `esp32c3,handshake-probe`.
`handshake-probe` includes the quiet timing integration. It stores a fixed ring
without synchronous packet prints; the example emits it after disconnect or
failure, including retries after successful local completion. Incoming key flags
are unverified metadata. Event 12 records authenticated retry acceptance and
event 13 its TX result. Event 11 in the controlled baseline is the private M4
omission hook. The recorder is global to a single station, resets per connection,
and uses wrapping microseconds; it is not a production multi-interface tracing API.

FoA CI passed all three workflows for the pinned revision: station replay
protection (`34582856289`), response queues (`34582856305`) and TX queue ownership
(`34582856291`). The retry verifier and production background handler are exercised
by twelve host tests, including the seven existing replay/routing regressions.
Ten response/recorder tests cover ownership, stale response filtering, timestamps
and ring retention. Both suites pass debug and release; CI uses Rust 1.90.0.

Exact ELF/application hashes, every retained trial, phase/event records and numeric
capture counts are in the JSON report. C3 normal recovery used local source matching
the published FoA code; dependency-pin crossbuilds are distinguished from device
runs. Raw logs, source snapshots, packets, firmware and signing material stay
private. S3 validation wrote only the existing signed application slot; the
bootloader, partitions and security settings were not changed.

The final S3 image used the published Git pin and completed all ten cycles.
A final C3 build with `foa-smoke` also passes with the diagnostic features disabled;
it was not flashed over the completed C3 recovery trial. The final S3 and normal
C3 trials showed no host duplicate replies and no gateway losses. These bounded
results do not establish long-term reconnect or rekey reliability.
The shared station code also passes locked release `cargo check` builds for
ESP32 and ESP32-S2 with `foa-smoke`; neither older chip was device-tested here.
The HAL C/Rust host regression script passes as well.
