# C3/S3 PHY wrappers and printf from source

This milestone replaces the small TX forwarding and USB state wrappers in
Rust and compiles the printf support library from its published MIT C source.
It retains the vendor RF initialization, calibration, channel tuning and RAM
power-tracking routines. No transmit-power policy, AGC address, retry schedule
or PHY callback table changes are part of this milestone.

The [wrapper review](PHY-WRAPPERS.md) records the original contracts and
exhaustive tests. The [printf source report](https://github.com/opensensor/esp-wifi-sys/blob/73add8985cec3b7582e6df80a4273022deb844b0/docs/SOURCE-PRINTF.md)
records its MIT provenance and fixes for bounded radio-log trimming, variadic
argument ownership and signed-minimum formatting. All 26 other C3/S3 archives
and the public bindings match the published sys 0.2.0 packages. The driver and
vendored PHY adapter both select that same Git revision, including for downstream
users of the driver. The examples also patch transitive registry references.

## Validation method

Tests ran on the connected C3 provisioner board and secured S3 on 11 September
2026. Updates wrote only the existing application slot. S3 applications were
signed with the board's existing key. Bootloaders, partitions and eFuses were
unchanged. Firmware, credentials, calibration data and raw network logs remain
private; the accompanying JSON records image/map/log hashes and sanitized results.

The comparison uses three station builds per chip: the current driver baseline,
source printf alone, and printf plus both Rust PHY wrappers. All use the same
FoA `39f4476` and smoltcp `517222f` corrections, release size optimization and
fat LTO. Builds used Rust `esp` 1.97.0.0 and Espressif C GCC 14.2.0
(`esp-14.2.0_20241119`); the S3 Rust link uses its installed GCC 15.2.0 driver.
C3 links with LLD. The same `network-trace,foa/tx-trace` features and log filters
were used throughout. Exactly one station was active at a time.

Each station run attempts ten WPA2/DHCP reconnect cycles, with twenty 512-byte
host echoes and twenty 512-byte gateway echoes in every cycle. First pings are
included; no ARP warmup or repeat-until-pass selection is applied. Host packet
captures are Ethernet-view ARP/ICMP evidence, not on-air monitor captures.
The application's completion assertion covers gateway echoes; host ping totals
are checked separately. Failures remain in the report.

## Station results and limits

| Chip / build | Completed traffic cycles | Host unique replies | Gateway replies | Result |
| --- | ---: | ---: | ---: | --- |
| C3 baseline | 10 | 200/200 | 200/200 | Complete |
| C3 printf only | 10 | 199/200 | 200/200 | App complete; one host reply missing |
| C3 combined | 10 | 200/200 | 200/200 | Complete |
| S3 baseline | 10 | 198/200 | 199/200 | Final gateway assertion failed |
| S3 printf only | 3 | 60/60 | 58/60 | Link dropped before DHCP completed in cycle 4 |
| S3 combined | 10 | 200/200 | 197/200 | Final gateway assertion failed |

No host duplicate replies were recorded in these six runs. These are individual
controlled observations, not proof of equivalent loss rates or a packet-loss fix.
S3 station reliability remains unresolved. The [sanitized report](phy-source-validation.json)
retains each image/map/log hash, all completed cycle totals, TX completion counts,
capture-drop counters and failed probes; it does not silently replace a failed
run with a later successful one.

The S3 baseline's missing host replies were received by the device, then evicted
from the eight-entry pending-response queue while ARP remained unresolved. The
first two ARP transmissions reported MAC success but did not appear in the host
capture. The third arrived after 2.0437 seconds and received a reply within
29 microseconds, allowing the remaining queued replies to drain. Capture socket
drops were zero. This identifies the queue overflow after preceding ARP delivery
loss; it does not establish why those first ARP frames disappeared.

In the S3 printf-only failure, authentication, association, EAPOL and the two
encrypted DHCP transmissions all completed successfully at the MAC. Other RX
continued before the link went down. With beacon timeout disabled and no
application disconnect requested, received deauthentication is the leading
source-level explanation; the reason was not logged, so it is not confirmed.
Prior stock-printf images also showed DHCP timeouts. No specific formatter fault
was identified: the failed ELF's radio-print callback is an empty return, and
the DHCP/FoA diagnostics use Rust formatting. A future connection-down trace
should expose a reason without logging key material.

The final combined S3 image has 504 matched TX start/finish pairs, with no
unmatched generations or MAC errors. Its missing gateway replies are cycle 1
sequence 1 (generation 29, `Ok(1)`), cycle 1 sequence 17 (generation 45,
`Ok(0)`) and cycle 9 sequence 20 (generation 451, `Ok(0)`). Each timeout has
an empty RX head and no corresponding received reply. MAC completion does not
prove delivery through the access point; the losses remain an open investigation.

## Linked dependencies

| Chip / station build | Allocated PHY bytes | Prebuilt printf bytes | Source printf bytes |
| --- | ---: | ---: | ---: |
| C3 baseline | 35,605 | 4,992 | 0 |
| C3 printf only | 35,605 | 0 | 5,700 |
| C3 combined | 35,593 | 0 | 5,700 |
| S3 baseline | 33,250 | 4,738 | 0 |
| S3 printf only | 33,270 | 0 | 4,966 |
| S3 combined | 33,238 | 0 | 4,966 |

All six images retain 18 PHY archive members and allocate no `libpp.a` inputs.
The combined images discard both original wrappers while retaining
`ram_tx_pwctrl_background` (122 / 78 bytes), `phy_param` (848 / 740 bytes) and
`register_chipv7_phy`. Input code, literals, data and BSS count only within live
ELF `SHF_ALLOC` sections; debug, discarded inputs and linker padding do not.
The [audit tool](tests/PHY-ALLOCATION-AUDIT.md) includes GNU `COMMON` and distinguishes
source printf from the prebuilt archive, backed by source and archive hashes.

S3 removes 32 vendor wrapper/literal bytes compared with printf alone. Compared
with the original baseline, the net PHY reduction is 12 bytes: linking source
printf changes retained shared literal pools by another 20 bytes. The affected
function-body sizes and vendor archive contents are unchanged; the
[literal-pool comparison](phy-source-s3-literals.json) records every affected
input and the original archive hash. This is a measured
link-layout effect, not removal of more analog code. Source printf itself is
larger than the original support library on both chips.

The first S3 full application link exposed cc-rs bundling printf into an earlier
Rust archive, before GNU ld saw the later PHY reference. Sys revision `73add89`
keeps printf unbundled and after the vendor archives. A freestanding consumer
regression using the actual sys archive reproduces the old missing `phy_printf`
error and passes on both chips after the fix. Crate-only builds had missed it.

## Device probes

The optional `printf-smoke` feature adds fourteen C ABI cases before Wi-Fi
initialization in `wifi_smoke`: integer, long long, floating point, native
`va_list`, width/precision, pointer formatting, signed minima and bounded output.
Final disassembly checks confirm that test calls reach allocated source-built
`snprintf` and `vsnprintf`, not ROM or libc replacements. Ordinary builds do not
include the test object. Formatter compatibility is limited to the tested source's
behavior; existing `%e` / `%g` quirks are deliberately retained.

`wifi_smoke` then scans, exhausts the ten RX buffers, preserves an unread completed
tail when a buffer returns, recovers reception, transmits an OFDM frame and checks
the MAC timer. `phy_lifetime_smoke` separately prepares the Wi-Fi domain using the
normal LL ordering, calibrates once, drops the sole PHY guard, and reacquires/releases
it twice more before initializing the MAC once and receiving beacons. The later
guard cycles exercise backup/shutdown/wakeup/restore; their calibration result is
cached from the first cycle. Station reconnects alone do not cover this lifecycle.

The first lifetime probe incorrectly required `CalibrationResult::Ok` and stopped
before any guard release on both chips. A C3 control using the original adapter
also returned `Some(DataCheckFailed)` and hit that assertion. This enum describes
the **input** calibration data: fresh zero-filled data fails the initial checksum
check even though FULL calibration generates updated output. Original C3 instructions
retain that initial status across RF initialization and calibration backup, then
return it unchanged. [ESP-IDF's PHY initialization](https://github.com/espressif/esp-idf/blob/67c1de1eebe095d554d281952fde63c16ee2dca0/components/esp_phy/src/phy_init.c)
likewise uses the status to decide whether refreshed calibration data must be saved.
The corrected probe records the status, requires available nonempty calibration
output, and retains its actual shutdown/wakeup and post-wakeup beacon checks.
The earlier failures are included as failed probe evidence, not lifetime passes.

Both corrected lifetime probes completed all three enable/release cycles with
nonempty calibration output, followed by three C3 and two S3 beacon receptions.
Both combined formatter/RX probes returned zero for all fourteen ABI cases,
preserved the unread pending tail, recovered the ten-buffer RX list and completed
OFDM TX and MAC timer checks. Their scan counts were six frames on C3 and
ten on S3. USB serial remained
available throughout initialization, RF shutdown and wakeup.

## Reproduce the probes

From `examples/`, use the installed target C compiler and matching archiver.
For the reviewed S3 toolchain, set these to the GCC 14.2.0 installation:

```sh
export CC_xtensa_esp32s3_none_elf=/path/to/bin/xtensa-esp32s3-elf-gcc
export AR_xtensa_esp32s3_none_elf=/path/to/bin/xtensa-esp32s3-elf-ar
ESP_LOG=info cargo +esp build --locked --release \
  --target xtensa-esp32s3-none-elf --features esp32s3,printf-smoke --bin wifi_smoke
ESP_LOG=info cargo +esp build --locked --release \
  --target xtensa-esp32s3-none-elf --features esp32s3,phy-smoke --bin phy_lifetime_smoke
```

For C3, use `CC_riscv32imc_unknown_none_elf` / `AR_riscv32imc_unknown_none_elf`
with `riscv32-esp-elf-gcc` / `riscv32-esp-elf-ar`, target
`riscv32imc-unknown-none-elf` and feature `esp32c3`. The station probe uses
`--features CHIP,network-trace,foa/tx-trace --bin sta_smoke`, build-time `SSID`
and `PASSWORD`, and `S3_SMOKE_CYCLES=10` on either chip. Preserve the documented
log filter when comparing the recorded station results:

```text
info,embassy_net=trace,smoltcp=trace,foa=debug,foa::tx_queue=trace,foa_sta=info
```

The production-source and original-instruction checks run in host CI through
`sh docs/esp32s3/tests/run-rust-tests.sh`. The allocation parser has nine
synthetic regressions, including shared-library naming and allocated COMMON.
Hardware testing remains distinct from those host checks.
