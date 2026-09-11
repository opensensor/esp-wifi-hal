# Source PHY tracking dispatcher on C3 and S3

The periodic TX-power wrapper now calls a Rust implementation of
`ram_tx_pwctrl_background`. The original dispatcher is no longer allocated in
either station image. Temperature, power, PLL and RF-calibration helpers remain
the original routines, operating on the initialized vendor state. Tracking
cadence, caller exclusion and the driver's `(1, 0)` arguments are unchanged.

The [original instruction inventory](PHY-POWER-CONTROL.md) defines the boundary.
[`phy_dispatcher.rs`](../../esp-wifi-hal/src/phy_dispatcher.rs) preserves each
chip's load widths, ordering, callback slots, fresh table/argument reads after
helpers, and the full enter/exit token. C3 retains the direct ROM power veneer
at `0x40001c2c` and RF threshold 20. S3 retains its single 32-bit gate read and
installed temperature/power callbacks. Raw volatile pointers avoid references
to vendor-owned mutable RAM. These private layouts are tied to the pinned sys
revision; updating that dependency requires reviewing them again.

## Independent comparison and target checks

Run:

```sh
sh docs/network/tests/run-phy-dispatcher.sh
sh docs/esp32s3/tests/run-rust-tests.sh
python3 docs/network/tests/test_audit_phy_allocations.py
```

The [bounded instruction interpreter](tests/phy-dispatcher-oracle/README.md)
executes the recorded original code with opaque analog boundaries. Its expected
traces are compared with the actual production generic Rust dispatcher at
optimization levels zero and two: 137,216 C3 cases and 268,288 S3 cases per
optimization level. These cover all byte argument pairs and gates, access
width/order, optional flags, full-width tokens and helper mutations of later
state and callbacks. Five malformed-evidence checks also run with Python
assertions disabled. This establishes the modeled dispatch contract; it does
not model RF calibration or prove the native pointer/ABI layer by itself.

Crossbuilt disassembly independently confirms native access widths, callback
slots, argument registers and preserved exit tokens. The S3 compiler adds
`memw` ordering instructions for volatile accesses. Neither instruction nor
timing identity is claimed. Linked production callers specialize `(1, 0)`;
the exhaustive host comparisons cover every valid byte pair.

## Device evidence

The [sanitized validation report](phy-dispatcher-validation.json) identifies
the exact images, logs, source hashes and build configuration. Baselines use
HAL `e6fce6cd8156ac9855a0cbde49c97046570c57e9`; all station images use FoA
`90cfad9b20dcd4ae121690d71c5393c4287506f6`, including the M1 retry recovery.
Only one station was active at a time. S3 application images were signed and
written to its existing app slot; security configuration was preserved.

Both chips pass the source printf ABI probe, initialization, pending RX
preservation, RX exhaustion/recovery, TX and beacon/OFDM reception. Separate
baseline and source lifetime tests pass three PHY enable/release cycles and
receive beacons after wakeup. Station reconnects alone do not test PHY guard
teardown.

An initial **unchanged S3 baseline** RX probe failed the pending-buffer identity
assertion. This failed trial is retained in the report. Diagnostic-only baseline
and source builds subsequently passed: both logged a 516-byte pending frame,
SIG_LEN 472 and delivery of the expected buffer. The extra probe logging keeps
the original assertions. The failed trial lacked descriptor SIG_LEN metadata,
so its cause remains unresolved; it is not evidence of a dispatcher regression
or a demonstrated RX fix. No production RX behavior was changed here.

The first source S3 station trial completed ten reconnects and all 200 gateway
echoes but returned 198/200 host echoes. In cycle five, host requests 1 and 2
went unanswered; an ARP exchange about 2.03 seconds after the first request
preceded a burst of replies to requests 3–10. Capture socket drops were zero.
PHY tracking peaked at 82 microseconds, so this does not show a long PHY stall.
The pinned smoltcp implementation has an eight-entry pending-response queue
which evicts the oldest entries when full. Its existing host overflow test
reproduces replies 3–10 after ten requests wait for ARP. That supports a queue
pressure explanation, but quiet device logs do not prove eviction, and the
Ethernet capture cannot locate an earlier ARP loss. Queue size was not changed.

All station trials, including fresh vendor/source follow-ups, are retained in
the report:

| Chip / dispatcher trial | Reconnects | Host echoes | Gateway echoes |
| --- | ---: | ---: | ---: |
| C3 source | 10 | 200/200 | 200/200 |
| S3 source, initial | 10 | 198/200 | 200/200 |
| S3 vendor, fresh control | 10 | 200/200 | 200/200 |
| S3 source, identical-image follow-up | 10 | 200/200 | 200/200 |

All four trials had zero host duplicates and zero capture socket drops. The
earlier published-pin M1 baseline also completed 200/200 echoes in both
directions on each chip and is included separately. The fresh S3 vendor
tracking maximum was 79 microseconds, compared with 82 in the initial source
trial. These short observations do not establish long-term loss equivalence.

Tests use
80 MHz, quiet logging, ten WPA2/DHCP reconnect cycles and twenty 512-byte host
and gateway echoes per cycle, without ARP warmup. Ethernet capture statistics
describe host ARP/ICMP observation, not an on-air EAPOL capture.

## Remaining binary dependencies

| Non-string allocated PHY input bytes | Vendor dispatcher baseline | Source dispatcher | Removed vendor inputs |
| --- | ---: | ---: | ---: |
| C3 | 35,593 | 35,471 | 122 |
| S3 | 33,238 | 33,156 | 82 |

The S3 reduction includes its 78-byte body and a four-byte literal. Both images
still allocate inputs from 18 PHY members. The source function bodies occupy
138 bytes on C3 and 110 bytes on S3; removed vendor bytes do not imply a total
firmware-size reduction. There are no allocated `libpp.a` inputs, and printf
continues to come from source.

The [allocation audit](tests/PHY-ALLOCATION-AUDIT.md) verifies the old dispatcher
is absent while its required helpers, parameter object, callback table and
calibration remain. This comparison explicitly excludes object-verified
mergeable strings on both sides: the S3 GNU map reports pre-merge string sizes
that cannot be attributed as unique linked ranges. Full default audits reject
those overlaps; the report does not present non-string totals as complete
archive attribution.

Long-duration RF performance, temperature/power sweeps, GTK rekey and new
pairwise exchanges remain outside this milestone. The unresolved baseline RX
probe failure also needs further investigation. This removes a bounded dispatch
body, not the remaining analog PHY or ROM dependencies.
