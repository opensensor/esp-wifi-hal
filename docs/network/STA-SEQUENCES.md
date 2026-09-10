# Assign a sequence to every generated station frame

The examples pin OpenSensor FoA
[`c83717ee`](https://github.com/opensensor/FoA/commit/c83717eeeeaa8c5b6e53743b868e27de4e55e9be),
which enables driver sequence assignment for established station data, EAPOL,
and authentication/association requests. Deauthentication already enabled it;
this station implementation scans passively and has no probe-request sender.

FoA created each 802.11 header with sequence zero, then passed MAC parameters
with `override_seq_num` disabled. The HAL deliberately leaves raw callers'
sequence numbers unchanged unless they opt in. The correction enables that
option at the three station-owned transmit initializers. It preserves raw API
defaults, ACK settings, retry limits, connection control flow and key handling.

The HAL assigns once before DMA setup and its retry loop. Retries of the same
MPDU retain its number; each newly queued frame gets another. Assignment precedes
hardware CCMP encryption, and EAPOL's MIC does not cover the modified 802.11
header. Independent review checked these paths and the actual serializer.
Both C3 and S3 trace-enabled station release builds linked successfully.

## Finding from the completion trace

The C3 baseline at `ff26efec` recorded 506 paired starts/completions. Every one
of its 456 protected transmissions completed with sequence zero. Authentication,
association and EAPOL also stayed at zero; deauthentication advanced from 0 to 9.
All driver completions succeeded: 461 without retries, 28 after one retry,
12 after two, three after three, one after four and one after six.

That baseline nevertheless completed ten cycles with 200/200 unique host replies
and 200/200 gateway replies, plus two duplicate host replies. Constant generated
sequences therefore remain a concrete correctness defect even in a passing ping
run. Host capture reported zero socket drops. Image and serial hashes are in
[C3 sequence evidence](sta-sequence-validation-c3.json).

## Corrected C3 device result

The corrected image completed ten WPA2/DHCP/reconnect cycles with **200/200
unique host replies and 200/200 gateway replies**. All 506 generated frame
completions had distinct sequence numbers, advancing exactly from 0 through 505.
That includes all 455 protected frames, authentication, association, EAPOL and
deauthentication. Every start paired with a successful completion: 473 without
retries, 26 after one, five after two and two after three. There were no
TX-exhaustion warnings or host capture socket drops.

The host received two extra duplicates, at cycle 5 sequence 4 and cycle 10
sequence 14. Both repeated requests and replies appear at the embassy boundary.
The sequence correction therefore does not eliminate all duplicate reception.
The S3 target stayed disconnected throughout this C3 run. Image SHA-256:
`ecc63512c19c7c221b46bbf818afcb60104d8f8e634e4f8f4de3b7d0813cdf28`.

## Corrected S3 sequence result and remaining loss

The secured S3 also confirms assignment: all 504 generated transmissions paired
with successful completions and sequences 0 through 503. Its single ten-cycle
run returned **199/200 host and 194/200 gateway replies**, with one duplicate
host reply. The final gateway assertion failed and the run remains recorded.

Every missing gateway request correlates to an `Ok(0)` completion: no retry was
needed, but no corresponding reply reached the receive boundary. The missing
host request also never reached that boundary. This verifies sequence assignment
while leaving a separate receive/delivery problem unresolved. The duplicate host
reply had one request/reply submission at the boundary and a transmission that
needed one retry; its path differs from the C3 duplicate incoming requests.
See [the S3 trace and exact correlations](../esp32s3/STA-SEQUENCES.md).

## Loss attribution and reproduction

A new frame reusing an earlier sequence can resemble an old retransmission when
the Retry bit is set. For example, [Linux's unicast duplicate filter](https://github.com/torvalds/linux/blob/v6.12/net/mac80211/rx.c#L1368)
checks Retry together with the previous sequence-control value. This is a
possible loss mechanism, not proof of the cause of an earlier gateway timeout.
Neither the AP's duplicate-filter decisions nor on-air Retry flags were captured.
The local HAL clears Retry before the completion trace reads the buffer, so that
trace alone cannot establish what flag was transmitted.

Use the [optional completion-trace build](TX-QUEUE.md#optional-mac-completion-trace)
and count every first ping. Compare `FOA_TX finish` sequence fields for distinct
queue generations, including frames that needed retries. Start events may still
contain the serializer's placeholder. A successful driver result is distinct
from IP delivery, and a clean ping repeat does not erase earlier failed runs.
The [FoA review notes](https://github.com/opensensor/FoA/blob/c83717eeeeaa8c5b6e53743b868e27de4e55e9be/tests/STA-SEQUENCES.md)
describe transmit-path coverage, crypto handling and the remaining Retry-bit question.
