# Packet-loss investigation

The `network-trace` example feature records ARP and IPv4 echo metadata at the
FoA/embassy-net boundary: direction, device time, identifier, sequence, length
and IP endpoints. It does not record payloads. `tx` means submitted to FoA,
not acknowledged over the air. The driver logs exhausted transmission errors
at warning level, including the queue and frame length. Connection failures
also capture bounded RX descriptor state on C3 and S3.

Build `sta_smoke` with `esp32c3,network-trace` (or `esp32s3,network-trace`) and
`ESP_LOG=info,embassy_net=trace,smoltcp=trace,foa=debug,foa_sta=info`.
Keep credentials in the build environment and images/logs private. In particular,
FoA STA debug logging can include WPA2 key material; leave that module at info.
Tracing adds latency and is diagnostic instrumentation, not a throughput benchmark.

## Baseline evidence, 2026-09-10

The three-cycle C3 baseline used driver `be22c0b` with packet instrumentation,
upstream smoltcp 0.13.1, WPA2, 512-byte payloads, and 20 host pings per cycle at
200 ms intervals. All 60 requests reached the device's IP stack. It submitted
58 replies, and host capture received all 58. Only sequence 1 in cycles 2 and 3
was missing; both requests reached the stack before its ARP exchange completed.
Cycle 1 had already learned the host through an incoming ARP request and
returned all 20 replies. Gateway traffic returned 60/60.

Image SHA-256:
`2433caf255173eaa8f3390e1fc866d7aecb9a91dcbd47b1b1a45470679e52132`.

A separate ten-cycle instrumented baseline returned **200/200 gateway** and
**191/200 host** replies. Packet captures again showed all 200 requests reaching
the device, with only the first response absent in cycles 2–10. All 191 submitted
responses arrived at the host. No later-packet loss reproduced in this run.
Counts and the image hash are in [packet-baseline-validation.json](packet-baseline-validation.json).

This locates the cold-neighbor loss inside the network stack. It does not
explain the earlier isolated later-packet loss, six-packet burst loss, or
intermittent connection/DHCP timeouts. Those failures remain part of the record.
Raw captures, firmware and serial logs remain private.

## Corrected queue

The pending-response fix now passes the ten-cycle C3 test with **200/200 host**
and **200/200 gateway** replies. Its first revision exposed and then fixed an
embassy-net integration issue: refreshing the same hardware address must preserve
pending replies. See [implementation and complete before/after evidence](../network/PENDING-RESPONSES.md).
This result includes the first ping and does not use ARP warming.
