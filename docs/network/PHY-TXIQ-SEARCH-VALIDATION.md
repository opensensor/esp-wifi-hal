# C3/S3 TX IQ search and calibration validation

Implementation `47b4b67d387291d589ec611eaa417bd18cd23f2a`; control `e30b267264cd0e93e936a2c0f9aed25a33db3eec`.

`txiq_cover` and `rfcal_txiq` now run in Rust on C3 and S3. Ten vendor TX calibration functions remain per chip. Both RX calibration archive members remain absent.

FoA/sys revisions, examples, logging and traffic settings are fixed between control and source. The optional TX probe is disabled in all sixteen builds.

## Software and linked firmware

- 1,616 original/model cases per chip cover all 278 C3 / 225 S3 original instructions and all 34 C3 / 24 S3 conditional edges. Production Rust matches at host O0/O2. Thirteen contract tests pass with normal and optimized Python.
- Eight final source application profiles pass 12,928 executions against the pinned originals. All 298 C3 / 319 S3 emitted instructions and 26 / 22 conditional edges per profile are covered, without exemptions.
- All sixteen source/lock checks and composed ownership gates pass. The 420 allocation tests also pass with optimized Python and no site packages. ESP32/S2 compatibility checks pass. Earlier local workflow results are included in the numerical report.
- The comparison preserves signed measurement arithmetic, denominator guards, early termination and exhaustion, chip-specific narrowing and access order, live and saved callbacks, coefficient clamps, and saved register restoration. Lower helper internals and Bluetooth RF behavior are outside this comparison.

| Chip/profile | Live vendor PHY before → after |
|---|---:|
| esp32c3 ordinary | 4014 → 3282 B |
| esp32c3 GTK | 4014 → 3282 B |
| esp32s3 ordinary | 3046 → 2436 B |
| esp32s3 GTK | 3046 → 2436 B |

Live vendor PHY counts exclude strings. The selected search/calibration text is removed; every retained input name and size agrees with control across all eight pairs. The two new Rust function bodies total 848 bytes on C3 and 829 bytes on S3, exceeding the removed function sizes.

esp32c3: selected original inputs remove 728, 732 bytes, depending on profile. All retained input names and sizes are unchanged.
esp32s3: selected original inputs remove 610 bytes, depending on profile. All retained input names and sizes are unchanged.

The first native build matched all observed traces but failed complete coverage because LLVM emitted redundant loop exits. The Rust loops were simplified and rebuilt as source-v2. Those initial images and failed coverage records are retained privately; none were flashed.

## Device comparison

The fixed eighteen-attempt plan contains eight lifetime/RX trials, paired ordinary and GTK station trials, and two ordinary-source restorations. Lifetime trials begin with invalid calibration input, perform three PHY lifetimes, and check calibration output and beacon reception. Existing entry probes check bindings passively; they do not count execution of each new function. Initialization and TX-gain fingerprints are compared separately.

| Chip | Trial | Router echoes | Gateway echoes | Broadcast | Multicast | GTK rotations |
|---|---|---:|---:|---:|---:|---:|
| esp32c3 | control-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32c3 | source-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32c3 | control-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 3 |
| esp32c3 | source-gtk-v1 | 300/300 | 20/20 | 119/120 | 120/120 | 3 |
| esp32c3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | control-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | source-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | control-gtk-v1 | 300/300 | 20/20 | 119/120 | 120/120 | 3 |
| esp32s3 | source-gtk-v1 | 300/300 | 20/20 | 120/120 | 120/120 | 3 |
| esp32s3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |

Completion markers: 18/18. Router echoes: 1440/1440; gateway echoes: 320/320. All attempts and measured gaps remain in the numerical report; no retry-until-pass selection.

Measured gaps in esp32c3 source-gtk-v1: router sequences []; group sequences {'broadcast': [41], 'multicast': []}.

Measured gaps in esp32s3 control-gtk-v1: router sequences []; group sequences {'broadcast': [62], 'multicast': []}.

esp32c3 source-gtk-v1 broadcast sequence 41 appears in both AP captures, 184.019 ms after the last completed GTK G2. This supplies temporal context; the Ethernet captures do not identify an RF or driver cause.

esp32s3 control-gtk-v1 broadcast sequence 62 appears in both AP captures, 664.281 ms after the last completed GTK G2. This supplies temporal context; the Ethernet captures do not identify an RF or driver cause.

esp32c3 GTK control/source RTT: median 10.505/16.055 ms, p95 84.970/84.014 ms, maximum 181.101/214.830 ms.

esp32s3 GTK control/source RTT: median 16.471/10.163 ms, p95 82.456/65.125 ms, maximum 122.666/244.684 ms.

## Remaining work

These finite tests use one board per chip and one AP. The instruction executor compares modeled boundary behavior; it does not establish analog RF, cycle timing, or long-duration reliability equivalence. Wi-Fi trials do not validate Bluetooth radio operation. AP Ethernet captures cannot locate a loss within the RF/MAC/driver/stack path. Earlier packet gaps, the failed C3 TX-detector restoration, and TX-probe timing tails remain open. This milestone makes no packet-loss or latency-fix claim.

The ten remaining vendor functions per chip are `txdc_cal_v70`, `bt_txdc_cal`, `txdc_cal_init`, `rfcal_txcap`, `tx_cap_init`, `rfcal_pwrctrl`, `tx_pwctrl_init_cal`, `tx_pwctrl_init`, `bt_tx_pwctrl_init`, and `bt_txpwr_freq`. Analog/ROM dependencies remain separate.

Only app slots were flashed, with forced chip/security checks and verified S3 signatures. Ordinary source images remain installed. Paired flashing leaves S3 held in ROM; the C3 terminal outcome is recorded in its restoration trial. Owned router workers/files are removed, monitor is disabled, and persistent AP configuration is unchanged.

See the [numerical evidence](phy-txiq-search-validation.json) and [reproducible oracle](tests/phy-txiq-search-oracle/README.md).
