# Router-originated station baseline

The 2026-09-12 baseline originates traffic on the AP itself, excluding the
host's separate 6-GHz connection from the echo path. Each chip completed two
WPA2/DHCP cycles with 40/40 router-to-station echoes and 40/40 station-to-router
echoes. This is a bounded baseline, not proof of long-duration or rekey support.

The [router echo source](tools/router-echo/echo.c) sends twenty 512-byte requests
at 200-ms intervals per cycle. It checks the reply source, identifier, sequence,
checksum, embedded send time and full payload pattern, and reports missing,
duplicate and invalid replies. A static AArch64 build passed a three-echo
router loopback preflight, then ran from a temporary RAM directory. It requires
raw-socket access and does not change radio or forwarding settings.

Build on a host with the AArch64 GNU toolchain:

```sh
aarch64-linux-gnu-gcc -static -O2 -Wall -Wextra -Werror \
  docs/network/tools/router-echo/echo.c -o router-echo
```

Run on the router using the current station's DHCP address:

```sh
./router-echo "$STATION_IPV4" 20 200
```

Per-reply `rtt_us` includes userspace receive scheduling on the router. The
final JSON object records counts and missing sequence numbers; exit status is
nonzero for missing/invalid replies or send errors. Destination identities and
packet payloads are omitted from stdout. Captures and device logs remain private.

The existing `sta_smoke` example defaults to a ten-second traffic window.
`STATION_TRAFFIC_SECONDS=90` extends each connected window for rekey testing;
the allowed range is 5–3600 seconds. The router command's count and interval
must fit inside that window. Extending the window does not itself test GTK
rotation: the test must separately observe an authenticated key exchange and
continued traffic under the resulting key.

Numeric evidence is in [`router-endpoint-validation.json`](router-endpoint-validation.json).
The two earlier isolated losses remain unresolved. The independent receiver's
coverage limitations and observed AP-to-host ARP delay remain documented in
[`RAW-CAPTURE.md`](RAW-CAPTURE.md).
