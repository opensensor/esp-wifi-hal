# Retain automatic replies while the neighbor resolves

The FoA examples now use OpenSensor's smoltcp 0.13.1 fork at
[`517222f7`](https://github.com/opensensor/smoltcp/commit/517222f7318c092d82197e2e68cfccca0f460b09)
and enable `iface-pending-responses` whenever `foa-smoke` is enabled.
The Cargo patch applies to embassy-net's smoltcp dependency as well as the example's
direct dependency. Tracing is optional and does not enable or disable the fix.

An automatic ICMP reply belongs to the interface, rather than a socket's transmit
queue. In unmodified smoltcp 0.13.1, a reply generated while its neighbor is unknown
causes an ARP request, returns `NeighborPending`, then disappears when the receive
buffer is released. The matching ARP reply cannot recover it. The same dispatch path
handles immediate TCP responses and IPv6 replies needing neighbor discovery.

The fork retains the generated payload before releasing the receive buffer and
retries it through the existing routing, neighbor validation, checksum and IPv4
fragmentation paths. It sends the original response after resolution, including its
identifier, sequence, payload and checksums. It does not warm ARP, generate an
extra ping, suppress the first measurement, or learn neighbor mappings from
arbitrary IP frames. Upstream removed that last behavior after actual gateway
cache poisoning on a misconfigured network; see
[smoltcp ARP fixes #544](https://github.com/smoltcp-rs/smoltcp/pull/544).
Retaining packets during ARP resolution is described in
[RFC 1122 section 2.3.2.2](https://www.rfc-editor.org/rfc/rfc1122.html#section-2.3.2.2).

## Bounds and scheduling

The feature uses eight fixed slots of 1500 payload bytes by default: approximately
12 KiB of additional interface storage, plus IP representations and timers. It
needs no allocator. `SMOLTCP_IFACE_PENDING_RESPONSE_COUNT` and
`SMOLTCP_IFACE_PENDING_RESPONSE_BUFFER_SIZE`, or the corresponding smoltcp Cargo
features, can tune those bounds. Payload size excludes the IP header.

Discovery uses the existing one-second rate limit. Responses expire after five
seconds and are cleared on interface IP or MAC reconfiguration. A full queue
evicts its oldest response; an oversized payload is dropped without evicting other
entries. Such limits remain packet-loss conditions and must not be reported as
guaranteed delivery through an unresponsive neighbor or sustained queue pressure.

`poll_at` and `poll_delay` include retry/expiry deadlines, even without sockets.
The split ingress/egress polling API also works. Each `poll_egress` attempts at most
one retained packet, discovery rotates between silent neighbors, and resolved
neighbors are serviced in arrival order. The queue applies to Ethernet, which is
the medium exposed by FoA's station device; it does not change IP-only or 802.15.4
dispatch.

## Adapter integration regression

The initial queue revision (`4b4b1bcc`) passed standalone tests but still lost replies
on both boards. embassy-net 0.9.1 calls `Interface::set_hardware_addr` with the same
address before every poll. Unconditionally clearing retained packets there discarded
them before ARP completed. The pinned revision clears the queue only when that
address actually changes. A new regression fails before the fix and passes after it;
the application reproduction also performs the repeated setter calls. The earlier
hardware results remain recorded, rather than being counted as successful validation.

## Host validation

Both commands require a host Rust toolchain at least 1.91. `+esp` supplies a suitable
host compiler on the development machine.

The historical unmodified-dependency reproduction remains available and expects
the first automatic reply to be lost:

```sh
cargo +esp test --locked --target x86_64-unknown-linux-gnu \
  --manifest-path docs/esp32s3/tests/neighbor-repro/Cargo.toml
```

The new reproduction pins the same fork revision as the firmware. It injects echo
1 with an empty neighbor cache, observes ARP, injects the answer, and requires the
original 512-byte reply with valid IP/ICMP checksums before testing echo 2:

```sh
cargo +esp test --locked --target x86_64-unknown-linux-gnu \
  --manifest-path docs/network/tests/pending-response-repro/Cargo.toml
```

The companion smoltcp commit also passed:

- All 656 upstream library tests with the feature enabled.
- Fifteen packet regressions covering original payload ownership, lost ARP retry,
  a six-reply burst, capacity/oversize behavior, expiry, route/configuration changes,
  TX backpressure, split polling, independent neighbors, discovery fairness,
  TCP reset, IPv6 NDISC/checksum, two concurrent fragmented IPv4 replies, and
  repeated unchanged MAC refreshes as performed by embassy-net.
- Twelve of those regressions with the minimal IPv4 feature set and no raw socket.
- `no_std` builds for RV32IMC and Xtensa ESP32-S3; the S3 check used IPv6-only plus
  `defmt`, exercising a separate feature configuration.

The integrated `sta_smoke` example also compiled and linked in release mode for
ESP32-C3 with `esp32c3,foa-smoke`, using dummy build-time credentials and no board
access. Its resolved dependency tree contains one smoltcp instance, shared with
embassy-net, at the pinned revision.

For the upstream suite and expanded regressions:

```sh
git clone https://github.com/opensensor/smoltcp.git
cd smoltcp
git checkout 517222f7318c092d82197e2e68cfccca0f460b09
cargo +esp test --lib --features iface-pending-responses \
  --target x86_64-unknown-linux-gnu
cargo +esp test --test pending_responses --features iface-pending-responses \
  --target x86_64-unknown-linux-gnu
```

These host tests establish the stack behavior. They do not establish radio
reliability, PHY replacement, or zero loss on a physical board. Device validation
must still correlate host capture with embassy-net RX/TX and MAC completion, with
the first host ping included.

## Separate connection-handshake observations

Reading the installed FoA/foa_sta 0.2.0 release's
[`operations/connect.rs`](https://github.com/opensensor/FoA/blob/cf2415b982b268730c50ea1059798fa3a6e1c197/foa_sta/src/operations/connect.rs)
revealed separate connection-path questions for follow-up.
Authentication/association performs bounded operation
retries and requests seven MAC retries, but discards the returned TX result before
waiting for the peer response timeout. EAPOL send completion treats a missing
completion record (`None`) as success, and the message-1/message-3 receive loops
have no internal deadline or EAPOL retransmission state machine. The example's
outer connection timeout still bounds the overall attempt.

None of those observations explains an already-connected automatic reply being
dropped on `NeighborPending`. This change does not alter WPA2 or connection retry
handling; those need separate tests and review.
