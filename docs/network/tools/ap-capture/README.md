# Filtered AP Ethernet capture

This is the exact receiver used for the [AP capture follow-up](../../AP-CAPTURE.md).
It was tested on a little-endian AArch64 router with Linux 4.19.183. It requires
raw-socket privileges and an Ethernet-format interface. It does not enable
promiscuity, change Wi-Fi settings, or disable forwarding acceleration.

Build with an AArch64 Linux cross compiler and static libc:

```sh
aarch64-linux-gnu-gcc -static -O2 -Wall -Wextra -Werror capture.c -o ap-capture
```

Place the binary in a temporary directory on the router, then run:

```text
ap-capture INTERFACE PEER_IPV4 SECONDS STOPFILE
```

Standard output is a classic Ethernet pcap; standard error contains JSON
readiness and final packet statistics. Use a fresh, nonexistent stop-file path.
Creating that file ends capture; SIGINT, SIGTERM or the 1–3600-second deadline
also ends it. The process reports capture drops, truncated packets and missing
kernel timestamps as a nonzero exit status. Capture files can contain private
network data and should stay outside publication artifacts.

The kernel BPF filter accepts ARP or IPv4 ICMP involving the selected peer.
`filter.h` was generated with:

```sh
tcpdump -ddd -y EN10MB 'arp host 192.0.2.1 or (icmp and host 192.0.2.1)'
```

At startup, the receiver substitutes the selected peer for that placeholder.
There is no VLAN or raw 802.11 decoder. Capture truncation is detected above the
1600-byte snapshot size. The pcap writer assumes little-endian byte order.

The station example randomizes its MAC at boot. Filtering on the wired host
allows capture to start before the station gets its new DHCP address; discover
the station identity separately for per-station AP counters. Check capture
coverage against successful echoes before interpreting an absent packet.
Hardware acceleration can bypass this socket path, and an Ethernet transmit
record is not proof that a frame was transmitted or acknowledged over the air.
