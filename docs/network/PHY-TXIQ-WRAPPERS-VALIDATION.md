# C3/S3 TX IQ wrapper validation

Implementation `f8bd3c6a8ee84049743dc256cd291eccbafc313a`; control `994e666e4ff50dd5dd86365c5d2d455b53e53ef8`.

`txiq_cal_init` and `bt_txiq_cal` now run in Rust on C3 and S3. Twelve vendor TX calibration functions remain per chip. Both RX calibration archive members remain absent.

FoA/sys revisions, examples, logging and traffic settings are fixed between control and source. The optional TX probe is disabled in all sixteen builds.

## Software and linked firmware

- 2,048 original/model cases per chip cover all 140 C3 / 92 S3 original instructions and all 10 C3 / 4 S3 conditional edges. Production Rust matches at host O0/O2. Nine contract tests pass with normal and optimized Python.
- Eight final source application profiles pass 16,384 executions against the pinned originals. All 134 C3 / 130 S3 emitted instructions and four edges per profile are covered, without exemptions.
- All sixteen source/lock checks and composed ownership gates pass. The 411 allocation tests also pass with optimized Python and no site packages. ESP32/S2 compatibility checks pass. Earlier local workflow results are included in the numerical report.
- The comparison preserves fresh flag reads, callback-table and slot reloads, full-word analog restores, and the eight-byte aligned scratch output. It checks C3’s wrapping Bluetooth byte adjustment and the different C3/S3 order of the final table read and flag write. Calibration helper internals and Bluetooth RF behavior are outside this wrapper test.

| Chip/profile | Live vendor PHY before → after |
|---|---:|
| esp32c3 ordinary | 4402 → 4014 B |
| esp32c3 GTK | 4402 → 4014 B |
| esp32s3 ordinary | 3304 → 3046 B |
| esp32s3 GTK | 3304 → 3046 B |

These counts exclude strings and describe live vendor PHY allocations, not total firmware size. Every retained input name is compared with control. All retained input sizes are unchanged in these eight control/source comparisons; the only removed inputs are the selected wrapper text and literals.

esp32c3: selected original inputs remove 388 bytes per profile; retained input sizes are unchanged.
esp32s3: selected original inputs remove 258 bytes per profile; retained input sizes are unchanged.

## Device comparison

The fixed eighteen-attempt plan contains eight lifetime/RX trials, paired ordinary and GTK station trials, and two ordinary-source restorations. Lifetime trials begin with invalid calibration input, perform three PHY lifetimes, and check calibration output and beacon reception. Existing entry probes check bindings passively; they do not count execution of each new function. Initialization and TX-gain fingerprints are compared separately.

| Chip | Trial | Router echoes | Gateway echoes | Broadcast | Multicast | GTK rotations |
|---|---|---:|---:|---:|---:|---:|
| esp32c3 | control-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32c3 | source-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32c3 | control-gtk-v1 | 299/300 | 20/20 | 120/120 | 120/120 | 3 |
| esp32c3 | source-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 3 |
| esp32c3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | control-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | source-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | control-gtk-v1 | 300/300 | 20/20 | 119/120 | 120/120 | 3 |
| esp32s3 | source-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 3 |
| esp32s3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |

Completion markers: 18/18. Router echoes: 1439/1440; gateway echoes: 320/320. All attempts and measured gaps remain in the numerical report; no retry-until-pass selection.

Measured gaps in esp32c3 control-gtk-v1: router sequences [64]; group sequences {'broadcast': [], 'multicast': []}.

Measured gaps in esp32s3 control-gtk-v1: router sequences []; group sequences {'broadcast': [21], 'multicast': []}.

esp32c3 GTK control/source RTT: median 13.991/9.978 ms, p95 81.803/81.141 ms, maximum 118.551/136.115 ms.

esp32s3 GTK control/source RTT: median 9.678/16.713 ms, p95 69.086/84.915 ms, maximum 149.385/169.385 ms.

## Remaining work

These finite tests use one board per chip and one AP. The instruction executor compares modeled boundary behavior; it does not establish analog RF, cycle timing, or long-duration reliability equivalence. Wi-Fi trials do not validate Bluetooth radio operation. AP Ethernet captures cannot locate a loss within the RF/MAC/driver/stack path. Earlier packet gaps, the failed C3 TX-detector restoration, and TX-probe timing tails remain open. This milestone makes no packet-loss or latency-fix claim.

The twelve remaining vendor functions per chip are `txdc_cal_v70`, `bt_txdc_cal`, `txdc_cal_init`, `txiq_cover`, `rfcal_txiq`, `rfcal_txcap`, `tx_cap_init`, `rfcal_pwrctrl`, `tx_pwctrl_init_cal`, `tx_pwctrl_init`, `bt_tx_pwctrl_init`, and `bt_txpwr_freq`. Analog/ROM dependencies remain separate.

Only app slots were flashed, with forced chip/security checks and verified S3 signatures. Ordinary source images remain installed. Paired flashing leaves S3 held in ROM; the C3 terminal outcome is recorded in its restoration trial. Owned router workers/files are removed, monitor is disabled, and persistent AP configuration is unchanged.

See the [numerical evidence](phy-txiq-wrappers-validation.json) and [reproducible oracle](tests/phy-txiq-wrappers-oracle/README.md).
