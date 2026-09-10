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

Unique successful replies and duplicate receipts are counted separately. A
follow-up audit of the retained ping logs found four duplicate host replies in
the initial queue run and two in the corrected run; these counts do not change
the unique-reply totals below.

| Queue revision | Completed cycles | Unique host replies | Gateway replies | First replies after reconnect | Duplicate host replies |
| --- | --- | --- | --- | --- | --- |
| `4b4b1bcc` | 10; final gateway assertion failed | 190/200 | 199/200 | 0/9 | 4 |
| `517222f7` | 10; application completed | 200/200 | 200/200 | 9/9 | 2 |

Image hashes, build flags, source hashes and all cycle results are in
[`pending-response-validation.json`](pending-response-validation.json).
Private addresses, credentials, signed firmware and raw logs are excluded.

This comparison tests one S3 and one WPA2 access point, with another C3 test
client sometimes active on the same AP. It does not establish long-duration
reliability or fix every reason a packet can disappear before reaching the IP
stack. Queue capacity, expiry and supported media remain the limits documented
in [the stack change](../network/PENDING-RESPONSES.md).


## Combined FoA and smoltcp queue validation

The follow-up image pins both `foa` and `foa_sta` to
`2985c2e5105a11047494885f75f33c3bcb3192e5` and smoltcp to
`517222f7318c092d82197e2e68cfccca0f460b09`. The FoA change addresses queue
generation and cancellation ownership. PHY and receive-driver source remain
unchanged from the previous S3 validation. The lockfile resolves exactly one
copy of each of those three crates from its selected revision.

Two runs used the same signed image, SHA-256
`67762d290b91cd42f6f72bc4977d37a2290940a0e155d39786de7d12eef2a690`.
The first ping remained included, with twenty 512-byte host pings at 0.2-second
intervals per cycle. No ARP warming or altered success criteria were used.

| Combined-image run | Completed cycles | Unique host replies | Gateway replies | Duplicate host replies | Application outcome |
| --- | --- | --- | --- | --- | --- |
| First attempt | 10 | 200/200 | 199/200 | 0 | Gateway assertion failed |
| Byte-identical repeat | 10 | 200/200 | 200/200 | 1 | Completed |

The first attempt lost gateway cycle 9, sequence 9. The request appears at the
FoA/embassy transmit boundary; its matching reply never appears at receive.
Other ARP traffic arrived during the wait, and the following gateway request
succeeded. The RX head was empty/incomplete at the timeout. There were no
transmission-exhaustion warnings, but this build does not record successful
per-frame MAC completions. It therefore cannot establish whether that request
was delivered over the air or acknowledged by the AP.

The repeat's duplicate was host cycle 1, sequence 5. Both duplicate request and
reply appear at the FoA/embassy boundary. Neither run reported payload/checksum
diagnostics. The earlier failure remains part of the image's result; the
successful repeat does not establish a cure for occasional packet loss or
duplicate delivery. C3 traffic could overlap these runs on the same AP.

The runs validate the combined integration under connection and traffic load.
They do not deliberately inject the generation/cancellation races addressed by
the separate FoA queue regressions. Complete per-cycle metadata, source hashes,
selected dependencies and the failed-run investigation are retained in
[`combined-queue-validation.json`](combined-queue-validation.json).
