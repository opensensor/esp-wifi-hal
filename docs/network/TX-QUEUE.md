# Preserve TX completion ownership and recover cancelled buffers

The examples pin both `foa` and `foa_sta` to OpenSensor FoA
[`2985c2e5`](https://github.com/opensensor/FoA/commit/2985c2e5105a11047494885f75f33c3bcb3192e5).
This revision corrects transmit queue ownership independently of the
[smoltcp pending-neighbor response fix](PENDING-RESPONSES.md), which remains
pinned at `517222f7318c092d82197e2e68cfccca0f460b09`.

## Failures reproduced in the original queue

Each caller's completion handle must belong to one generation of a ring slot.
The original implementation expired a handle at exactly one full queue of
insertions, although its slot was still current. Reusing a slot also inherited
the previous caller's completion-interest flag, and dropping a stale handle
could clear the replacement caller's flag. A caller could consequently miss a
valid result or wait indefinitely.

Cancellation exposed two more ownership problems: the runner saved an interest
flag before awaiting the radio, and dropping an already completed handle left
its frame retained. Enough abandoned completions could hold every actual TX
buffer, preventing subsequent allocation even when the queue appeared empty.

The correction resets interest at enqueue, checks generation before cancellation,
and checks current interest after hardware completion. Dropping an unclaimed
completed frame returns its buffer and wakes blocked allocators. Pending and
active frames retain ownership until transmission finishes. An aborted runner
resolves its waiter with `None`. The generation counter rejects exhaustion before
mutation instead of wrapping into incorrect non-power-of-two ring indices.

No additional buffers or per-slot fields are required. Authentication,
association, EAPOL, and retry behavior are unchanged. In particular, a valid
peer response can still be received after local transmission reports a missing ACK.

## Host validation

The locked harness compiles the actual production queue and TX buffer pool with
real embassy synchronization. A controlled endpoint substitutes for the radio
and exercises success, ACK failure, delayed completion and cancellation.
All fifteen tests pass with eight buffers in debug and three buffers in release.
The same harness reproduces eleven failures against the original `cf2415b` queue.
An independent review reproduced both passing configurations.

```sh
git clone https://github.com/opensensor/FoA.git
cd FoA
git checkout 2985c2e5105a11047494885f75f33c3bcb3192e5
./tests/run-tx-queue.sh
./tests/run-tx-queue.sh --release --features small-pool
```

The tests cover ring reuse, stale handles, mixed awaited/fire-and-forget traffic,
payload and result preservation, cancellation before/during/after transmission,
full-pool recovery, actual waker notification, aborted runners and counter
exhaustion. See the [FoA test documentation](https://github.com/opensensor/FoA/blob/2985c2e5105a11047494885f75f33c3bcb3192e5/tests/TX-QUEUE.md).

The host failures establish concrete queue defects. They do not establish that
these defects caused every earlier connection timeout or missing radio packet.
Device validation combines the corrected queue with Rust PHY controls and the
smoltcp fix; its results must retain failures as well as passing repeats.

## Combined device validation, 2026-09-10

Each run used ten WPA2/DHCP/reconnect cycles with twenty 512-byte host pings
per cycle at 200 ms intervals, followed by twenty gateway pings. The first host
ping was always included; there was no explicit ARP warm-up. Repeats used the
same image bytes as their first run.

| Target/run | Unique host replies | Gateway replies | Host duplicates | Final assertion |
| --- | --- | --- | --- | --- |
| C3 first | 200/200 | 199/200 | 0 | Failed |
| C3 identical repeat | 200/200 | 200/200 | 1 | Passed |
| S3 first | 200/200 | 199/200 | 0 | Failed |
| S3 identical repeat | 200/200 | 200/200 | 1 | Passed |

The C3 first run lost gateway cycle 4 sequence 16; the S3 lost cycle 9 sequence 9.
Both requests reached the network TX boundary but no matching reply reached RX.
Adjacent replies continued, with no TX-exhaustion warnings and an empty/incomplete
RX head at each timeout. These builds record submission rather than successful
MAC completion, so they cannot establish delivery or an acknowledgement by the AP.
C3 and S3 traffic could overlap during the first runs; the C3 repeat ran with
the S3 disconnected. Repeats do not retroactively turn the failed runs into passes.

The C3 filtered host capture recorded no socket drops in its first run. All
host requests and replies reached the corresponding network boundaries and host
ping logs. Trace logging adds timing overhead, and these are bounded functional
tests rather than throughput or long-duration reliability measurements.

Image hashes, per-cycle outcomes and capture limits are in
[C3 results](tx-queue-validation-c3.json) and
[S3 results](../esp32s3/combined-queue-validation.json).
