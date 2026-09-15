# C3/S3 TX IQ measurement validation

Implementation `6947b15d2c6616f08afc73e5d349f78ac104c208`; control `ab8d3921196c4213a313cf57e488dcd85f5c904b`.

`txiq_get_mis_pwr` and `get_power_atten` now run in Rust on C3 and S3. Fourteen other vendor TX calibration routines remain per chip. Both RX calibration archive members remain absent.

FoA and sys revisions, example code, logging and traffic settings are fixed between control and source. The optional TX probe is disabled in all sixteen builds.

## Software and linked firmware

- 1,654 original/model cases per chip cover every original instruction (177 C3 / 130 S3) and all 18 conditional edges per chip. Production Rust matches at host O0/O2; eleven contract tests pass normal/optimized Python.
- Eight final source application profiles pass 13,232 executions against the pinned originals: all 175 C3 / 154 S3 emitted instructions and all 18 conditional edges per profile are covered, without exemptions.
- All sixteen build-source/lock checks and composed ownership gates pass. The 402 allocation tests pass with optimized Python and no site packages; ESP32/S2 compatibility checks pass. Local host regression outcomes are included in the numerical report.
- The original ELF/map extraction is reproduced. Ordered volatile accesses, halfword outputs including aliasing, signed narrowing, six-sample limit, backoff and convergence are compared. C3 retains fresh callback-table dispatch; S3 retains its distinct direct adjustment and extra 2us delay.

| Chip/profile | Vendor PHY before → after |
|---|---:|
| esp32c3 ordinary | 4852 → 4402 B |
| esp32c3 GTK | 4852 → 4402 B |
| esp32s3 ordinary | 3663 → 3304 B |
| esp32s3 GTK | 3663 → 3304 B |

These are live non-string vendor PHY allocations, not total firmware size. C3 lifetime/RX profiles retain 4,398 bytes. The four extra bytes in C3 station profiles come from wider calls in retained `txiq_cover`. The retained `rfcal_txiq` and `tx_cap_init` calls each grow two bytes in all C3 profiles. Complete retained-body comparisons verify the same logical call targets and internal branches. A relocated `CSWTCH.166` channel table is checked for its exact three-byte contents, extent, readonly allocation and calculated address. The initial strict address mismatch was retained and resolved before flashing.

## Device comparison

The fixed eighteen-attempt plan contains eight lifetime/RX trials, paired ordinary and GTK station trials, and two ordinary-source restorations. Lifetime trials begin with invalid calibration input, perform three PHY lifetimes, and check calibration output and beacon reception. Existing entry probes are passive binding checks, not counters proving each new function ran. Initialization and TX-gain fingerprints are compared separately.

| Chip | Trial | Router echoes | Gateway echoes | Broadcast | Multicast | GTK rotations |
|---|---|---:|---:|---:|---:|---:|
| esp32c3 | control-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32c3 | source-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32c3 | control-gtk-v1 | 300/300 | 20/20 | 120 | 120 | 3 |
| esp32c3 | source-gtk-v1 | 300/300 | 20/20 | 120 | 120 | 3 |
| esp32c3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | control-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | source-normal-v1 | 40/40 | 40/40 | — | — | — |
| esp32s3 | control-gtk-v1 | 300/300 | 20/20 | 120 | 120 | 3 |
| esp32s3 | source-gtk-v1 | 300/300 | 20/20 | 120 | 120 | 3 |
| esp32s3 | source-restored-v1 | 40/40 | 40/40 | — | — | — |

Completion markers: 18/18. Router echoes: 1440/1440; gateway echoes: 320/320. All attempts and measured gaps remain in the numerical report; no retry-until-pass selection.

esp32c3 GTK control/source RTT: median 8.114/11.947 ms, p95 35.825/27.058 ms, maximum 83.315/67.399 ms.

esp32s3 GTK control/source RTT: median 5.191/10.278 ms, p95 27.042/39.668 ms, maximum 92.668/103.360 ms.

## Limits and retained dependencies

These finite tests use one board per chip and one AP. The original-instruction executor checks modeled boundary behavior; it does not prove analog RF, cycle timing or long-duration reliability equivalence. AP Ethernet captures do not locate a loss within the RF/MAC/driver/stack path. Earlier packet gaps, including the failed C3 TX-detector restoration, and the TX-probe timing tails remain open. This replacement is not a packet-loss or latency fix.

The remaining vendor functions per chip are: `txdc_cal_v70`, `bt_txdc_cal`, `txdc_cal_init`, `txiq_cover`, `rfcal_txiq`, `bt_txiq_cal`, `txiq_cal_init`, `rfcal_txcap`, `tx_cap_init`, `rfcal_pwrctrl`, `tx_pwctrl_init_cal`, `tx_pwctrl_init`, `bt_tx_pwctrl_init`, and `bt_txpwr_freq`. Analog and ROM helper boundaries remain separate.

Only app slots were flashed, with forced chip/security checks and verified S3 signatures. Ordinary source images remain installed. Paired flashing leaves S3 held in ROM; C3 terminal outcome is recorded with its restoration trial. Owned router workers/files are removed, monitor is disabled, and persistent AP configuration is unchanged.

See the [numerical evidence](phy-tx-iq-measure-validation.json) and [reproducible oracle](tests/phy-tx-iq-measure-oracle/README.md).
