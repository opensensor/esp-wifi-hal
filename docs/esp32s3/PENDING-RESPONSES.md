# S3 pending-response queue hardware comparison

The S3 station test compares two revisions of OpenSensor's smoltcp pending-response
queue with the reviewed Rust PHY helpers from `f89c704`. Both builds enable
`esp32s3,network-trace`, use the same ten-cycle FoA application and record the
FoA/embassy packet boundary. The first of every twenty host pings is counted;
there is no explicit ARP warm-up or discarded measurement. Each ping carries a
512-byte payload. The gateway socket test runs after the host traffic window so
it cannot prime the host test's neighbor cache.

## The initial integration failure

The first queue revision, `4b4b1bcc4894539e1b9f7f6f24dbc3d5c455320f`, passed the
standalone queue regression but still lost the first host echo after each
reconnect on hardware. Embassy-net 0.9.1 refreshes the interface's hardware
address during polling. The initial queue implementation cleared pending replies
on every `set_hardware_addr` call, even when the address was unchanged.

The S3 trace for cycles 2 through 10 shows this sequence:

```text
RX: ICMP echo request, sequence 1
TX: ARP request for the host
RX: host's ARP reply
RX: ICMP echo request, sequence 2
TX: ICMP echo reply, sequence 2
```

Reply 1 never reached the transmit boundary. Across ten completed cycles, that
build received 190/200 host replies and 199/200 gateway replies. Besides the nine
first-reply losses, host cycle 8 lost sequence 16, which never appeared at the RX
boundary. Gateway cycle 7 lost sequence 2: its request appeared at TX, but its
reply did not appear at RX. There were no exhausted-transmission warnings. The
final application assertion failed because of the gateway loss. These additional
losses are recorded separately from the pending-response integration bug.

## Preserve replies across an unchanged hardware address

Revision `517222f7318c092d82197e2e68cfccca0f460b09` preserves pending replies when
the hardware address is unchanged, while retaining invalidation on an actual
address change. Its regression covers the Embassy-style repeated setter call.
The same S3 cycle-2 trace now contains:

```text
       0 us  RX: ICMP echo request, sequence 1
  10,440 us  TX: ARP request for the host
  27,336 us  RX: host's ARP reply
  39,197 us  TX: original ICMP echo reply, sequence 1
```

The identifier and sequence match the original request, and the host receives
that first reply. Packet metadata is captured at the FoA/embassy boundary;
the host check establishes reception beyond that boundary. The standalone
regression separately checks the retained 512-byte payload and IP/ICMP checksums.

The corrected run completed all ten cycles with **200/200 host replies and
200/200 gateway replies**. All ten first host pings arrived. In reconnect cycles
2 through 10, the trace explicitly records reply 1 transmitted after the host's
ARP answer. No transmission-exhaustion warnings occurred in this run.

| Queue revision | Completed cycles | Host replies | Gateway replies | First replies after reconnect |
| --- | --- | --- | --- | --- |
| `4b4b1bcc` | 10; final gateway assertion failed | 190/200 | 199/200 | 0/9 |
| `517222f7` | 10; application completed | 200/200 | 200/200 | 9/9 |

Image hashes, build flags, source hashes and all cycle results are in
[`pending-response-validation.json`](pending-response-validation.json).
Private addresses, credentials, signed firmware and raw logs are excluded.

This comparison tests one S3 and one WPA2 access point, with another C3 test
client sometimes active on the same AP. It does not establish long-duration
reliability or fix every reason a packet can disappear before reaching the IP
stack. Queue capacity, expiry and supported media remain the limits documented
in [the stack change](../network/PENDING-RESPONSES.md).
