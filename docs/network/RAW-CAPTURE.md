# Independent C3 capture of the S3 station

The C3 receiver now captures the S3's WPA2 handshake and encrypted data,
with asynchronous USB transport and explicit loss counters.
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

The fresh fifty-reconnect trial also completed: **1,000/1,000 host echoes and
1,000/1,000 gateway echoes**, using the byte-identical earlier `burst32-final`
signed S3 image. Both AP radio interfaces captured all 1,000 host requests and
replies. The C3 produced decrypted matches for 990 requests and 998 replies,
with 5,244 frame records and zero USB corruption, sequence gaps, queue drops or
oversize records. Its ten missing request matches include the first request
before station selection; other gaps occur after selection. These are gaps in
independent observation, not lost pings. The per-cycle list is retained so
clean USB transport cannot be mistaken for complete radio coverage.

The published Python recorder was separately exercised on the physical C3
native USB port for a bounded twenty-second run after the paired trial: five
frame records, a valid final marker, and zero transport errors. Host checks
cover fragmented serial input, CRC recovery, missing records, terminal markers,
counter consistency and MPDU preservation; OpenSensor CI `34704824757` passed.

## A captured one-second ARP delay

Cycle 42 retained five pending responses with a maximum queue wait of 1,007 ms.
All were dispatched, with no eviction or expiry. The first echo's host RTT was
1,025.24 ms; the next four replies arrived together after waits of approximately
821, 614, 411 and 202 ms. Later echoes returned normally.

The first S3 ARP request appears about 12 ms after the first echo on both AP
radio captures, and about 6 ms after it on the C3 capture. The host capture has
no matching first ARP request. It sees the next request about 1,014 ms after
the echo and responds immediately. AP captures show the repeated request about
996 ms after the first. Each relative timeline is anchored by the same complete
echo identity; absolute clocks are not compared.

This locates the observed stall between the AP's forwarding observations and
host reception, rather than a second spent preparing the S3's first ARP request.
The existing response queue preserved the burst during that delay. The evidence
does not distinguish AP driver/firmware delivery, the 6-GHz radio link, or host
receive processing. Neither the first Ethernet observation nor the C3 capture
proves a successful on-air ACK on the host link. This event does not explain the
two older isolated losses.

## Topology and interrupted trials

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
