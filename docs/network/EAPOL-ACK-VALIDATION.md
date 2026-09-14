# Unicast EAPOL ACK waiting

FoA `9178988e373d14084dab06bde4f6bc679d4753e8`; HAL pin `0284ccb4bb5abf3249fa8fe0f15892e5c22d39d6`. Control: HAL `ddfe06dda0d4c674bb1a3c5045662f8460e43cc2`, FoA `c433109960bc2b346a45da47c2bd3d2cb32690bf`.

The shared EAPOL sender requested seven retries but left `wait_for_ack` at its false default. The radio could report transmission completion without waiting for an ACK, so a missing ACK could not trigger the intended retry path. Ordinary station data already enabled ACK waiting.

The sender now explicitly requests ACKs for its unicast EAPOL frames. Sequence assignment, retry count, key-slot selection, clear M4 behavior, protected group framing and PN allocation are unchanged. ACKs do not prove AP decryption or EAPOL acceptance.

## Regression and build evidence

The host harness compiles the actual production serializer and senders and mocks only radio submission/completion. The new ACK assertion fails all three sender tests on the old code; they pass after the fix. Replay/routing (31 tests) and response/reconnect (10) pass debug/release. TX queue tests pass with the default pool (15), a three-buffer release pool (15), and metadata tracing (17). All three FoA branch CI workflows pass.

Four new source builds and four reused control images have verified source/lock records. Only the FoA pin changes in the HAL manifests/lock. All eight composed allocation gates pass with identical retained PHY input names/sizes. The four new source images pass 20,124 RF-IQ native instruction cases. ESP32/S2 compatibility checks pass.

## Fixed device comparison

Same quiet logging, 80 MHz CPU, AP and traffic profile. One control/source rekey trial per chip, followed by two ordinary source restoration trials. No retry-until-pass selection.

| Chip | Trial | Router echoes | Gateway echoes | Broadcast | Multicast | Rekeys | Missing G2 at AP |
|---|---|---:|---:|---:|---:|---:|---|
| esp32c3 | control-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 3 | [] |
| esp32c3 | source-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 3 | [] |
| esp32c3 | source-restored-v1 | 40/40 | 40/40 | — | — | — | — |
| esp32s3 | control-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 3 | [] |
| esp32s3 | source-gtk-v1 | 300/300 | 20/20 | 119/120 | 119/120 | 3 | [] |
| esp32s3 | source-restored-v1 | 40/40 | 40/40 | — | — | — | — |

esp32s3 source-gtk-v1 missed broadcast sequence 62. It is present in both AP Ethernet captures. It followed the last captured G2 by 632.128 ms.

esp32s3 source-gtk-v1 missed multicast sequence 2. It is present in both AP Ethernet captures. It preceded the first captured group rekey.

Both control and ACK-enabled trials captured every group request and reply. This comparison therefore does not measure a reduction in EAPOL loss. The regression establishes the ACK-policy defect and its correction; the two S3 group-packet losses remain unexplained.

The numerical report retains every group-key update and retry, locally reported reply result, both capture streams’ EAPOL ordering and all request intervals. A completed rekey may include an AP retry. Missing replies are not discarded from the results.

## Timing and limits

- esp32c3 control/source router RTT median 4.028/7.027 ms; p95 16.637/28.417 ms; maximum 57.202/70.062 ms.
- esp32s3 control/source router RTT median 3.053/3.338 ms; p95 17.861/17.989 ms; maximum 43.284/117.826 ms.

This finite comparison tests the ACK-policy change; it does not establish a general packet-loss or timing fix. Earlier broadcast losses and latency tails remain open. Per-frame GTK INFO logging remains present and can affect timing. No RF capture or calibrated analog measurement was made.

Ordinary ACK-enabled applications restored on both boards, using app slots only and verified S3 signatures. Owned router workers/files removed, monitor disabled, persistent AP configuration unchanged. Paired flashing leaves S3 held in ROM with the ordinary source app retained; C3 completed and disconnected.

See [numerical evidence](eapol-ack-validation.json) and the preceding [RF-IQ comparison](PHY-RF-IQ-VALIDATION.md).
