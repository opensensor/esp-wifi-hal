# CTS failures and the next transmit diagnostic

The C3 Retry-only station run completed 506 queued transmissions. Two final
results were `Err(MacProtocol(CtsTimeout))`, corresponding to recorded missing
packets. The driver's CTS decoder branches agree with the vendor dispatch.
The run did not retain raw PMD values or individual attempt results, so this
does not establish why the exchange failed or which preceding attempts failed.

This is a follow-up record, not a change to RTS policy, retry limits, PHY
settings or error classification. It is separate from the
[Retry-bit restoration](MAC-RETRIES.md) and later packet-number validation.

## Recorded run and active policy

| Transmission | FoA generation / assigned sequence | Length before FCS | Final result | Packet correlation |
| --- | --- | --- | --- | --- |
| C3 station request | 85 / 85 | 588 bytes | `CtsTimeout` | Gateway cycle 2, sequence 6 missing |
| C3 automatic reply | 163 / 163 | 588 bytes | `CtsTimeout` | Host cycle 4, sequence 4 missing |

All 506 start/finish pairs used hardware queue 2. Final results were 445
`Ok(0)`, 34 `Ok(1)`, 11 `Ok(2)`, 3 `Ok(3)`, 6 `Ok(4)`, 2 `Ok(5)`, 3
`Ok(6)` and the two errors. `Ok(n)` is the successful attempt index; it is
not a count of on-air retransmissions, since channel-access failures also
consume attempts. There were no raw `PMD:`, SRC or LRC trace records.

Provenance for this historical run:

- Station ELF SHA-256:
  `166e95834a7aecc5878cfb680958e60e52585fbdf319a7d77f9e242cef86bd71`.
- Serial artifact label: `mac-retry-fixed-ten-20260911-000409.serial.txt`;
  SHA-256 `372799931c997dda71973b65b8d2186b866ce481847e6c28144f9230e2cc58b6`.
- Reviewed Retry implementation SHA-256:
  `b838b0b3883d6ba0b2b563ec63eaf556cf2f7e1c6812d7d0109ac6d43b19a9f3`.
- FoA station behavior corresponds to
  `c83717eeeeaa8c5b6e53743b868e27de4e55e9be`. Network logs and firmware remain
  private; the table above contains only diagnostic metadata.

`foa_sta` creates these transmissions with default `RtsStrategy::DriverControlled`,
`wait_for_ack: true`, and `RetryBehaviour::RetryUntil(7)`. The driver enables
RTS for a unicast receiver address. Its iterator therefore allows eight total
attempts at the same rate. FoA initializes and resets that rate to OFDM
6 Mbps, and this station example does not override it. These settings come
from the source; the old trace does not independently record the per-attempt
rate or RTS register value.

The active path does **not** use `MultiRateRetry` or HT rate fallback. On both
C3 and S3, the OFDM-6 hardware rate and configured response rate are `0x0b`.
The same C3/S3 PLCP1/misc encoding path is used. No demonstrated chip-specific
defect was identified in that active rate-setting path during this bounded
review. A final CTS error after the retry loop means the allowed attempts
were exhausted, not that all eight attempts necessarily ended in CTS errors.

## Vendor decoder evidence and a separate mismatch

The reference archives are the installed `esp-wifi-sys` 0.2.0 `libpp.a`
files. These are used as binary evidence; the open station images do not
allocate their code.

| Chip | `libpp.a` SHA-256 | `lmac.o` SHA-256 |
| --- | --- | --- |
| C3 | `a752442af19cbe70c349446dc26065561a911a29a7b28ccc805321c3a1b2ca84` | `f4b2cc74be33bc538ea5aed84cd09d468a4e3b24dac020536329770463203824` |
| S3 | `0af323b9be8eeee7b40c43460535614cf7a9ef6be99600c4318523bf342fd8b4` | `56de5f62c33e7c03dfc4cbbffecbc4082fcdafdeafd7fdee900ce51220b94b3b` |

C3 `lmacProcessTxComplete` extracts `(pmd >> 12) & 15`. Its `.L497`
jump-table relocations map class 2 to `.L499`, which calls
`lmacProcessCtsTimeout`, and class 4 to `.L498`, which passes the low PMD byte
to `lmacProcessTxError` with its third argument zero. The latter's subcode-zero
branch also calls `lmacProcessCtsTimeout`. These are the two CTS branches in
Rust's `LowLevelDriver::get_tx_mac_protocol_result`.

Disassembling `lmacProcessTxError` in both chip archives establishes the
following dispatch for that normal completion path (third argument zero):

| PMD class 4 subcode | Vendor dispatch | Current Rust result |
| --- | --- | --- |
| `0` | `lmacProcessCtsTimeout` | `CtsTimeout` |
| `1` | `lmacProcessCollision` | `Unknown` |
| `2` | `lmacProcessAckTimeout` | `AckTimeout` |
| `3`, `4`, `5` | `lmacProcessCollision` | `AckTimeout` |
| `0xc0` | Key-error handling | `InvalidKeyId` |
| `6..255`, except `0xc0` | `lmacProcessAckTimeout` | `Unknown` |

The collision branch has different behavior when the vendor function's third
argument is nonzero; the table must not be generalized to that caller context.
Observed dispatch to a function named `lmacProcessCollision` also does not
establish that the correct public Rust result is the existing top-level
`ChannelAccessError::Collision`. PMD errors and channel-access interrupt
errors belong to different stages of transmission.

This is a concrete classification difference, but it does not invalidate the
recorded CTS labels or establish delivery causality. Raw PMD is missing, so the
run cannot show whether another attempt encountered one of these subcodes.
In the current Rust loop, ACK versus other MAC errors changes SRC/LRC
accounting, but both branches advance the contention window once. Those
counters do not gate the retry count. Consequently, a change in the reported
class does not by itself demonstrate a change in packet delivery.

A future classification patch should first use original-instruction dispatch
fixtures covering all low-byte values, both relevant caller contexts and the
class-2/class-4 boundary. Tests should exercise the actual production decoder,
preserve unknown cases deliberately and verify any effect on retry handling.
An API decision for collision reporting requires review before implementation.

## Minimal next diagnostic

The existing log sites can provide a useful first discriminator without
changing RTS or retry policy. Add these narrow targets to the **build-time**
environment for a bounded diagnostic image:

```sh
ESP_LOG='info,foa::tx_queue=trace,esp_wifi_hal::ll=trace,esp_wifi_hal::async_driver::private=trace'
```

`esp_wifi_hal::ll` currently emits raw PMD and AIFSN/backoff values. The
`async_driver::private` target emits SRC/LRC updates and exhaustion results;
FoA supplies queue generation and safe frame-header metadata. The selected
driver trace sites contain no keys, addresses or packet payloads. Do not
broaden this to `foa_sta` debug logging. Existing application/network logs
remain private.

With only queue 2 active, the PMD records between a FoA start/finish pair
identify MAC-result classes, while the setup/backoff records count attempts
that fail channel access without producing PMD records. Verify that single
active queue assumption: the existing PMD line lacks a queue or attempt tag,
so interleaved queues would make this correlation ambiguous. The rate remains
source-derived unless a dedicated trace records it.

If that is insufficient, use a bounded metadata record per attempt containing
queue, generation or sequence, attempt index, rate, RTS/ACK flags, channel
result and raw PMD. One additional ordering question is worth distinguishing:
the vendor completion routine snapshots PMD **before** clearing the TX state,
while current Rust calls `tx_done` before reading PMD. Capture a diagnostic
snapshot around that existing clear before deciding whether the order matters;
do not change the order based on this observation alone. Emit after the
critical operation, or retain a small bounded trace for later output, to limit
logging interference.

The discriminator is whether a missing packet follows repeated CTS-class
results, other MAC classes, channel-access failures or a successful MAC
completion without a received reply. It does not identify an RF cause by
itself. Keep logging changes controlled and preserve loss, duplicate and
completion counts separately when comparing runs.
