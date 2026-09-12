# Router-originated traffic tools

`echo.c` validates 512-byte ICMP echo payloads at a configurable interval.
`group.c` sends labeled 128-byte datagrams to port 5005: limited broadcast and
the local multicast group 239.255.42.99 (TTL 1). The latter is received by
`sta_smoke` with `gtk-rekey-probe`; payload kind, sequence, pattern, source and
destination are checked on the MCU. Its JSON counts describe sends, not delivery.

```sh
aarch64-linux-gnu-gcc -static -O2 -Wall -Wextra -Werror echo.c -o router-echo
aarch64-linux-gnu-gcc -static -O2 -Wall -Wextra -Werror group.c -o router-group
```

Copy binaries into a temporary RAM directory on the router, then launch after
the station reports `stage=traffic_ready`:

```sh
./router-echo "$STATION_IPV4" 300 200
./router-group "$ROUTER_LAN_IPV4" 120
```

Run the two commands concurrently for the recorded mixed-traffic exercise.
Use the current DHCP address: the station example randomizes its MAC at boot.
No output includes network identities or packet payloads. Router echo requires
raw-socket privilege. The sender uses only the local test network.

For AP capture, compile the existing [`capture.c`](../ap-capture/capture.c) in a
temporary build directory with `group-filter.h` renamed to `filter.h`. This
extends the original ARP/ICMP selector with UDP/5005 and EAPOL. The filter was
generated with `tcpdump -ddd -y EN10MB` from:

```text
ether proto 0x888e or (host 192.0.2.1 and (icmp or arp or udp port 5005))
```

The capture program substitutes the runtime router IPv4 for 192.0.2.1. Capture
both the target radio's Ethernet interface and its bridge, using the existing
`capture IFACE IPV4 SECONDS STOPFILE` interface. These captures include EAPOL
for other stations on that radio; retain them privately and select the test
station before reporting counts. Record final socket-drop, truncation and
timestamp counters, and stop/remove the temporary tools after testing.
Use a fresh stop-file name for every chip and trial, and reject a zero-packet
capture even if its drop counters and process exit code are zero.
