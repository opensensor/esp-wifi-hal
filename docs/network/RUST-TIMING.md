# Console logging and Rust radio servicing latency

The S3 diagnostic stack was spending tens of milliseconds in synchronous console
calls around packet processing. `esp-println` 0.16.1 formats and writes each
record under `esp_sync::RawMutex`, which disables interrupts on the current core.
Its USB FIFO path waits for space while holding that lock. This substantially
distorts the latency of the code being measured.

The packet wrapper also used INFO for each packet, so selecting `ESP_LOG=info`
did not suppress that traffic when `network-trace` was enabled. Packet metadata
now uses TRACE and skips its timestamp/parsing work when disabled. Normal INFO
output retains cycle boundaries and failures. Explicit packet tracing remains
available through `ESP_LOG=info,examples::packet_trace=trace`.

An optional `timing-probe` feature adds fixed-size counters for console-call
duration, success-interrupt-to-task delay, PHY tracking duration and RX timestamp
age. It prints cumulative summaries after disconnect or before a connection/DHCP
panic. It adds no new per-packet or interrupt console output. Default builds have
no timing counters. The probe's default profile is `quiet`.

## Device comparisons

All trials use the same S3, AP, corrected clock and response parser, PHY tracking
cadence, queue sizes and deadlines. Each attempts ten reconnect cycles with
twenty 512-byte host and twenty gateway pings per traffic cycle. The first ping
counts; no ARP warmup is added. Only one station is active at a time. No failed
trial is replaced with a successful repeat.

| Profile / CPU | Traffic cycles | Host replies | Gateway replies | Median host RTT | Completion |
| --- | ---: | ---: | ---: | ---: | --- |
| Full trace / 80 MHz | 5 | 100/100 | 98/100 | 38.20 ms | DHCP timeout in cycle 6 |
| Legacy INFO packet output / 80 MHz | 10 | 200/200 | 200/200 | 26.10 ms | Complete |
| Quiet / 80 MHz | 6 | 120/120 | 120/120 | 9.455 ms | Connection timeout in cycle 7 |
| Quiet / 160 MHz | 10 | 200/200 | 200/200 | 10.30 ms | Complete |

The first trace trial recorded a maximum console call of **42,503 us**, with
**14.085 seconds** spent in 2,156 measured calls before its DHCP failure.
Maximum success-interrupt-to-task delay was **43,287 us**. PHY background
tracking took at most **80 us** across 63 calls. The reduced-output trial's
maximum task delay was **3,036 us**, and quiet mode's was **3,043 us**.
Those measurements establish a concrete console latency problem; one successful
ten-cycle comparison does not establish a general loss-rate fix. Quiet mode's
connection failure remains an unresolved validation result.

The quiet 160-MHz trial completed all ten cycles. Its maximum console call was
4,193 us and maximum measured task delay was 2,400 us. Host p95 RTT was 31.8 ms
versus 104.0 ms in the traced trial. All four host captures report zero socket
drops, and no duplicate host replies were observed. Both quiet profiles delivered
every attempted traffic ping; their different reconnect outcomes do not isolate
CPU speed as the cause of the 80-MHz connection failure.

S3's default Rust CPU configuration is **80 MHz**, while the earlier reviewed C
control's SDK configuration specifies **160 MHz**. The optional probe accepts
`TIMING_CPU_MHZ=80` or `160` to compare them without changing production defaults.
The earlier C control remains a different full stack and lifecycle; its clean
ping totals are not an instruction-for-instruction timing reference.

The sampled MAC/system timestamps differ only by the short sequential-read
interval (at most 14 us across these snapshots). Both counters advance in
microseconds. esp-rtos 0.3.0 selects the
1,000,000-Hz Embassy time driver and returns its system monotonic time directly.
No millisecond/microsecond scale mismatch was demonstrated. This sampling does
not validate every hardware ACK/SIFS/TSF timer or rule out scheduler races.

## Measurement boundaries

- Console duration includes formatting, lock acquisition and transport wait.
  It is not a direct measurement of the exact interrupt-masked interval. Summary
  output and direct vendor printf calls are outside that counter.
- TX delay starts when the success ISR signals the queue and ends when its task
  consumes success. Time waiting to enter the ISR is additional and unmeasured.
- RX age is the wrapping MAC counter minus raw RX metadata timestamp at driver
  delivery. It includes scanning and connection traffic, so its maximum is not
  the maximum ICMP forwarding delay. Non-yielding key derivation before
  authentication is a separate timing boundary worth measuring.
- Counter fields are independent atomics. Read while traffic is idle; snapshots
  are not transactional. Counts and total microseconds wrap at 32 bits.
- Histograms use exclusive upper bounds of 100, 1,000, 10,000 and 100,000 us,
  followed by an unbounded bucket. Every snapshot includes count, total and max.
- Device images predate the final INFO-to-TRACE severity cleanup. Their exact
  hashes and source hashes are retained; final crossbuilds are recorded separately.

The [sanitized evidence](rust-timing-validation.json) contains every trial,
timing snapshot, cycle total, failure, capture-drop count and source/image hash.
Raw captures, network identities, logs, firmware and signing material stay private.

Later phase measurements identified roughly one second of synchronous PMK
derivation per connection at 80 MHz. The [PSK preparation follow-up](PSK-PREPARATION.md)
records moving that calculation before radio startup and reusing the fixed
network's key during reconnects. The console measurements above remain a
separate source of latency.

## Reproduce

With the existing private build-time SSID/password environment and chip toolchain
configured, run from `examples`:

```sh
TIMING_LOG_PROFILE=quiet TIMING_CPU_MHZ=80 S3_SMOKE_CYCLES=10 \
  cargo +esp build --locked --release --target xtensa-esp32s3-none-elf \
  --features esp32s3,timing-probe --bin sta_smoke
```

Change only `TIMING_LOG_PROFILE` to `trace` for the full diagnostic target
filters, or `info` to reproduce the intermediate packet-output profile. The
probe uses these explicit filters instead of `ESP_LOG`; `foa_sta` stays at INFO
to avoid handshake key dumps. The intermediate profile explicitly enables the
packet target even though its records now use TRACE. For the CPU comparison,
keep `quiet` and select `TIMING_CPU_MHZ=160`.

Do not increase connection/ARP deadlines or alter radio tracking cadence based
on these counters. The remaining quiet-mode connection failure requires its own
handshake/queue evidence. Removing synchronous packet output from normal logging
corrects the measured interference without asserting that every loss is fixed.

The [handshake follow-up](EAPOL-RETRANSMIT.md) measures PMK derivation separately
and reproduces ignored M3 retransmissions after a lost M4. It adds authenticated M3
retry recovery while preserving the original timing trials and their failures.
