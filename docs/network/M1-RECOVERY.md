# Recover a lost WPA2 message 2

The station examples now pin FoA
`90cfad9b20dcd4ae121690d71c5393c4287506f6`. When waiting for M3, the initial
handshake recognizes a same-exchange M1 retry and resends M2 using the existing
SNonce/KCK and received EAPOL counter. Previously those retries were discarded.
The [implementation and host tests](https://github.com/opensensor/FoA/blob/90cfad9b20dcd4ae121690d71c5393c4287506f6/tests/M1-RECOVERY.md)
describe framing, nonce/counter validation and the unauthenticated M1 boundary.
Codex assisted the source investigation, Rust implementation and tests.

## Controlled loss and normal traffic

A private hook suppressed the first outgoing M2 once while reporting local
success. With the preceding FoA revision, S3 received three M1 retries near
1.019, 2.020 and 3.021 seconds after connection start. The initial M3 wait
discarded them and the connection timed out. The recovery S3 answered a retry
near 1.035 seconds, then completed DHCP and traffic. C3 answered its retry near
1.020 seconds and also completed. No AP configuration changed.

| Chip / trial | Completed cycles | Host replies | Gateway replies | Outcome |
| --- | ---: | ---: | ---: | --- |
| S3, omit first M2, baseline | 0 | — | — | Connection timeout waiting for M3 |
| S3, omit first M2, recovery | 1 | 20/20 | 20/20 | Complete |
| C3, omit first M2, recovery | 1 | 20/20 | 20/20 | Complete |
| S3, published pin, normal traffic | 10 | 200/200 | 200/200 | Complete |
| C3, published pin, normal traffic | 10 | 200/200 | 200/200 | Complete |

Every trial is retained in [m1-recovery-validation.json](m1-recovery-validation.json).
Both normal runs have zero host duplicate replies. All captures report zero
socket drops. Tests used one active station, quiet logging, an 80-MHz CPU,
twenty 512-byte host echoes and twenty gateway echoes per traffic cycle, and
no host ARP warmup. The existing traffic windows, connection/DHCP deadlines,
PHY cadence and PSK preparation behavior were preserved.

The injected builds used local source recorded against the published revision;
the normal ten-cycle images use the final Git dependency pin. The private
omission hook is absent from published source. C3's first injected crossbuild
failed because its temporary hook used a core atomic swap unavailable on that
target; the test hook was rebuilt using portable-atomic. It was not a device
trial or a production-code change. Neither failed device evidence nor build
logs were replaced with successful output.

## Reproduction and limits

From `examples`, with private `SSID` and `PASSWORD` build variables and the
chip toolchain configured:

```sh
TIMING_LOG_PROFILE=quiet TIMING_CPU_MHZ=80 S3_SMOKE_CYCLES=10 \
  cargo +esp build --locked --release --target xtensa-esp32s3-none-elf \
  --features esp32s3,handshake-probe --bin sta_smoke
```

For C3 select `riscv32imc-unknown-none-elf` and `esp32c3,handshake-probe`.
The recorder's kinds 14 and 15 identify an accepted same-exchange M1 retry and
the resulting M2 TX status. M1 remains unauthenticated; the subsequent M3 must
authenticate and pass nonce/counter/GTK validation before connection completion.
Private event kind 11 with argument 2 identifies the injected omission.

FoA's 22 replay/handshake/PSK tests and ten response/recorder tests pass in debug
and release. All three FoA CI workflows passed: replay `34602798674`, responses
`34602798651`, TX ownership `34602798606`. A probe-disabled C3 release crossbuild
and locked ESP32/S2 release checks pass; those builds were not flashed.

Ethernet captures supply ARP/ICMP evidence, not wireless EAPOL recordings. The
station's in-memory recorder supplies handshake evidence. Public artifacts
contain numeric results and hashes, not credentials, raw packets, keys, logs or
firmware. Only existing application slots were flashed; S3 used its existing
signing/security checks. Both boards disconnected after their completed runs.

GTK rekeying, changed-ANonce restarts and new pairwise exchanges remain separate
work. This is bounded lost-M2 recovery, not a complete WPA2 state machine or a
long-term reliability claim. No additional PHY or ROM code was replaced here.
