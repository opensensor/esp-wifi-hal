# Prepare the WPA2 key before radio startup

The station example now derives its fixed network's PSK once before `foa::init`
and reuses `Credentials::PreSharedKey` for subsequent connections. It pins FoA
`cf84eff3082afe054f85dd543d7aef7e60949a0a`, which exposes the existing derivation
through `Credentials::derive_psk(ssid)`.

Previously each connection performed synchronous PBKDF2 while radio tasks were
running. The preceding quiet 80-MHz trials measured about 1.13 seconds per S3
connection and 0.94 seconds per C3 connection in that phase. Preparation keeps the
first calculation at startup and removes its repetition from the reconnect path.
It does not accelerate PBKDF2 or make it asynchronous. Applications that pass
`Credentials::Passphrase` directly still derive a key during each connection.

This is application-owned key reuse for one fixed SSID/passphrase. There is no
global credential cache. Derive a new key whenever the SSID or passphrase changes,
and keep the returned bytes private. The four-way handshake and fresh session
state still run on each connection. No cryptographic primitive, iteration count,
CPU default, PHY tracking interval, queue size or connection deadline changed.
The [FoA API and host coverage](https://github.com/opensensor/FoA/blob/cf84eff3082afe054f85dd543d7aef7e60949a0a/tests/PSK-PREPARATION.md)
describe the implementation. Codex assisted the Rust and test work.

## Device comparison

Measurements use one active station, quiet logging and an 80-MHz CPU. Each
connection has twenty 512-byte host echoes and twenty gateway echoes, with the
same traffic windows as the previous tests and no ARP warmup before the host test.
The comparison baseline is the retained normal-recovery trial from
[EAPOL-RETRANSMIT.md](EAPOL-RETRANSMIT.md), not a newly rerun baseline. Both new
images use the published FoA Git pin. The C3 baseline used matching local source,
as documented in that earlier report.

| Chip | Prior PMK phase per connection | One-time startup preparation | Prepared PMK phase per connection |
| --- | ---: | ---: | ---: |
| ESP32-S3 | 1,129,733–1,129,758 us | 1,128,458 us | 20–26 us |
| ESP32-C3 | 937,398–937,419 us | 935,706 us | 25–29 us |

The startup number measures the one-time `derive_psk` call. The connection number
is the existing recorder's PMK phase (phase 2 minus phase 1), including overhead
around the raw-key copy. Neither is a complete connect/DHCP duration or an on-air
packet timing. The once-only preparation log contains only elapsed microseconds.

Both chips completed all ten reconnect cycles, each receiving **200/200 host**
and **200/200 gateway** replies. There were no host duplicate replies, and both
captures recorded zero socket drops. Median host RTT was 7.94 ms on S3 and
8.875 ms on C3. The prior medians were 7.63 ms and 9.25 ms respectively;
these short runs establish removal of repeated key derivation, not an improvement
in steady-state ping latency. No failed trial was discarded or replaced.

## Reproduce and limits

From `examples`, with private `SSID` and `PASSWORD` build variables and the chip
toolchain configured:

```sh
TIMING_LOG_PROFILE=quiet TIMING_CPU_MHZ=80 S3_SMOKE_CYCLES=10 \
  cargo +esp build --locked --release --target xtensa-esp32s3-none-elf \
  --features esp32s3,handshake-probe --bin sta_smoke
```

For C3 use `riscv32imc-unknown-none-elf` and `esp32c3,handshake-probe`.
Preparation also runs with the diagnostic features disabled. The C3 `foa-smoke`
release crossbuild passes without probes; locked release checks pass for ESP32
and ESP32-S2. Those builds were not device-tested. The HAL C/Rust regressions
pass, and the FoA host suite passes fifteen tests in debug and release, including
an independently verified PSK vector, changed credentials and repeated reuse.
FoA CI passed station replay (`34600741022`) and TX ownership (`34600741013`).

Exact build/image hashes, phase records and sanitized numeric capture counts are
in [psk-preparation-validation.json](psk-preparation-validation.json). Ethernet
ARP/ICMP captures check traffic; they do not capture on-air EAPOL. The station's
in-memory recorder supplies handshake evidence. Raw logs, packets, firmware and
credentials remain private. S3 validation uses its existing signed application
slot; bootloader, partitions and security configuration are unchanged.

These are bounded reconnect tests, not long-term reliability or rekey validation.
The earlier M3 retry recovery remains in place. Repeated M1 handling while waiting
for M3, GTK rekeying and new pairwise exchanges remain separate work. This change
does not replace any additional PHY/ROM code.
