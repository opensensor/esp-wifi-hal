# Independent C3 capture of the S3 station

The C3 receiver now captures the S3's WPA2 handshake and encrypted management/
data exchange, with asynchronous USB transport and explicit loss counters.
The [Rust example and host tools](tools/raw-capture/README.md) are included.
The production S3 station code is unchanged. This milestone supplies a measured
observation path; it does not explain or fix the two earlier isolated losses.

The initial paired trial captured zero selected frames despite clean USB and
40/40 successful host echoes. Diagnostic headers confirmed the correct AP's
beacons. Explicitly disabling unicast/multicast blocking and BSSID checking on
interface 0 allowed station frames through. Address filter banks remain
disabled and selection uses software; the receiver does not associate, install
keys or call the transmit API.

The corrected two-reconnect trial returned 40/40 host echoes. Both AP radio
interfaces captured all 40 requests and replies. The C3 captured and decrypted
39 of each, matching complete echo payloads as well as addresses, identifiers
and sequences. The missing pair is cycle 1, sequence 1, before the host learned
the station's randomized MAC and supplied it to the receiver. There were zero
USB CRC errors, sequence gaps, queue drops or oversize records. Handshakes and
retry frames are retained privately; counting a retry twice cannot inflate
coverage. Detailed counts and hashes are in
[`raw-capture-validation.json`](raw-capture-validation.json).

The host is connected over 6-GHz Wi-Fi through AP `eth9`; the S3 uses 2.4 GHz,
channel 3, through `eth10`. Both are captured, plus `br0`. Earlier references
to a wired host were incorrect: the previous host captures have been checked
against the current host Wi-Fi MAC. The old `eth2` capture was outside the host
path. See the correction in [`AP-CAPTURE.md`](AP-CAPTURE.md).

A fifty-reconnect trial was interrupted by a reported breaker trip. Its
captures lack final records and are excluded. The next attempt rejected an
empty receiver image left on disk before writing the device; the retained ELF
and existing signed S3 image matched their recorded hashes. The receiver image
was regenerated from that ELF for a fresh trial. No failed or interrupted
trial counts as successful validation.

The C3 is an independent observer, not proof that another radio received a
frame. Control frames and ACKs are excluded; clean USB counters alone cannot
establish complete RF or DMA coverage. A missing observed frame requires
correlation with host/AP evidence and the established capture window. The
receiver PCAP clock is MCU delivery time, while the AP and host clocks also
differ; packet identity and payloads establish correspondence.

Only existing, security-checked application slots were written. Raw captures,
credentials, signing material, network identities and firmware images remain
private. The S3's secure boot configuration is preserved.
