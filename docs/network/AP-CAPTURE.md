# AP-side reconnect capture

The 2026-09-12 follow-up reuses the exact application image bytes from the
earlier normal C3/S3 trials. It adds observation at the router, with no extra
MCU instrumentation. Each run uses quiet 80-MHz firmware, fifty reconnects,
twenty 512-byte host echoes and twenty gateway echoes per cycle, and one active
test station. The two earlier isolated normal-run losses remain unexplained;
passing repeats with unchanged firmware do not establish a fix.

| Board | Reconnects | Host replies | Gateway replies | AP host requests captured | AP host replies captured |
| --- | ---: | ---: | ---: | ---: | ---: |
| esp32s3 | 50 | 1000/1000 | 1000/1000 | 34 | 680 |
| esp32c3 | 50 | 1000/1000 | 1000/1000 | 50 | 1000 |

The S3 AP capture covers cycles 17–50. Its initial capture used a prior boot's
identity; this example randomizes its MAC at boot and receives a new DHCP
address. Those empty files remain private evidence of an invalid selector.
A subsequent attachment stopped on a switch pseudo-interface reporting
`Network is down`. The valid attachment excludes that interface. The C3 capture
starts before boot, filters on the host's stable address, and discovers the
station's current MAC for the AP counter sampler. The S3's first sixteen
cycles have host evidence but no valid AP coverage.

The AP is a GT-AXE16000 using its 2.4-GHz interface on channel 3, with Broadcom
driver 17.10.188.6401. A temporary static AArch64 AF_PACKET receiver runs from
RAM and filters ARP/ICMP before the socket queue. The [tested receiver source](tools/ap-capture/README.md)
is included. It records kernel timestamps,
socket drops and truncation, and streams its output over SSH. The preflight
captured all six frames of three host/router echoes. Successful retained AP
captures have zero socket drops, truncations or missing kernel timestamps.
No radio or forwarding settings change during these trials.

The AP wireless interface captures only the first outgoing host echo request
of each observed cycle. Its flow-cache status reports hardware acceleration
enabled with a one-packet activation deferral, consistent with this coverage
gap. The bridge and wired-interface traces do not cover these bridged host
echoes. Their missing records cannot establish packet loss. This is Ethernet
observation around the AP driver, not proof of on-air transmission, reception
or an 802.11 ACK.

The host and router clocks differ substantially. Correlation matches echo
direction, identifier, sequence and payload identity, then estimates the clock
offset from common packets; neither clock is changed. Counter samples cover
AP retries, retry exhaustion and decryption failures. Their observed maxima,
all cycle coverage, capture counters and image/log hashes are recorded in
[`ap-capture-validation.json`](ap-capture-validation.json).

After both baseline runs finished, a brief vendor active-monitor capability
check returned `wl: Not Permitted`. The mode stayed at zero and no monitor
interface appeared. An exit trap and a bounded watchdog both requested the
original disabled mode; it was verified again after the watchdog finished.
This firmware did not expose raw capture through that command. An independent
receiver or another supported raw-capture path is needed for on-air evidence.

Firmware images, credentials, keys, addresses, raw captures and serial logs
remain private. The earlier failures and their unresolved status remain in
[`RECONNECT-RX.md`](RECONNECT-RX.md). A recurrence outside the demonstrated
capture coverage still needs raw wireless or independent receiver evidence.
