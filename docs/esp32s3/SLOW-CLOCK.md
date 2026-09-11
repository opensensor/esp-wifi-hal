# Measured S3 Wi-Fi slow-clock calibration

The S3 OS adapter now returns the selected clock's calibration instead of the
fixed value `44462`. This corrects configuration supplied to MAC initialization;
it does not remove another PHY blob or establish a packet-loss fix.

| Clock selection | Returned calibration |
| --- | --- |
| `0x600c002c` bit 26 set: divided XTAL | `4096`, one microsecond with 12 fractional bits |
| Bit 26 clear: RTC slow clock | Measured `RTC STORE1` at `0x60008054`, shifted right seven bits |

The callback preserves the ESP-IDF contract, including truncation and a zero
return when the stored measurement is zero. It does not change clock selection
or initiate calibration. C3 already uses its separate select register at
`0x600c0024`; the C3 implementation and all radio-library pins remain unchanged.

## Original source and compiled instructions

The reference is ESP-IDF revision
`67c1de1eebe095d554d281952fde63c16ee2dca0`:

* [`esp_coex_common_clk_slowclk_cal_get_wrapper`](https://github.com/espressif/esp-idf/blob/67c1de1eebe095d554d281952fde63c16ee2dca0/components/esp_coex/esp32s3/esp_coex_adapter.c)
  selects the branch and converts the system's 19 fractional bits to Wi-Fi's 12.
* [`esp_clk_slowclk_cal_get`](https://github.com/espressif/esp-idf/blob/67c1de1eebe095d554d281952fde63c16ee2dca0/components/esp_hw_support/esp_clk.c)
  calls `clk_ll_rtc_slow_load_cal`; its S3 HAL implementation reads
  `RTC_SLOW_CLK_CAL_REG`, aliasing `RTC_CNTL_STORE1_REG`.
* S3 register headers place `SYSTEM_BT_LPCK_DIV_FRAC_REG` at system base
  `0x600c0000 + 0x2c`, with `SYSTEM_LPCLK_SEL_XTAL` at bit 26. RTC STORE1 is
  RTC base `0x60008000 + 0x54`. Bit 27 selects XTAL32K and must not take the
  divided-XTAL branch.

The existing SDK objects independently confirm the reference's machine-level
behavior. Their hashes, function bytes and literal bytes are preserved in
[`slow-clock-evidence.json`](slow-clock-evidence.json).

| Original wrapper operation | Instruction evidence |
| --- | --- |
| Load select-register address | `l32r` from literal `0x600c002c` |
| Read selected clock | `memw; l32i.n` |
| Prepare XTAL result | `movi.n a2, 1; slli a2, a2, 12` |
| Skip RTC read when XTAL selected | `bbsi a8, 26` to return |
| Read stored calibration otherwise | Call getter: `l32r` literal `0x60008054`; `memw; l32i.n` |
| Convert Q19 to Q12 | `srli a2, a10, 7` |

The actual dependency, `esp-hal` 1.1.2, defines `RtcClock::CAL_FRACT = 19` in
`src/clock/mod.rs`. Clock initialization calls `calibrate_rtc_slow_clock`,
measures 1024 cycles of the configured slow-clock source against XTAL, and
writes the resulting period to STORE1. The same file documents the stored
unit as microseconds with 19 fractional bits. Thus the adapter consumes the
measurement already produced by normal HAL initialization.

## Source, host tests and link verification

The production change is the S3 branch in `ffi::slowclk_cal_get` and a small
read-only helper in `s3_phy.rs`. Its existing volatile `u32` read helper retains
the peripheral access ordering. Every invocation reads the current selector;
only the RTC branch reads STORE1. No read is cached and no register is written
by the callback.

Run `sh docs/esp32s3/tests/run-rust-tests.sh`. The new tests execute the actual
Rust helper against the original IDF C formula, adapted only at its register
read boundary. Each of two optimization levels checks 3,212 selector/period
combinations: individual selector bits, varied unrelated fields, zero, seven-bit
truncation boundaries, measured-style values, the sign bit and `u32::MAX`.
They compare the complete ordered register-read trace as well as the return
value. Separate cases verify the skipped RTC read, XTAL32K distinction, fresh
measurements on successive calls and absence of writes. Substituting the old
constant `44462` fails all three new clock tests. Existing PHY, MAC, DMA and C3
regressions also pass.

The S3 `sta_smoke` crosslink passes with `esp32s3,foa-smoke`, dummy credentials,
one configured cycle and `ESP_LOG=info`. Its exact ELF/map hashes are in the
evidence JSON. The compiled FFI callback contains `memw` before each peripheral
load, the bit-26 branch, a logical right shift by seven and the alternate
`4096` result. It contains no new peripheral store. This is build evidence;
that dummy-credential image has not been flashed.

`s3_mac::init` already supplies this callback to `hal_timer_update_by_rtc`.
That helper enables bit 25 at `0x60035024` and stores the calibration's low
18 bits at `0x60035058`; its behavior is unchanged. Device validation should
record the selected source, raw STORE1 measurement, returned Q12 value and
programmed MAC field, then check existing station and RX-recovery behavior.
The code and host checks alone do not establish timing accuracy during modem
sleep or explain the existing intermittent packet losses and disconnects.

## Device validation, 11 September 2026

The secured S3 ran the source-clock image using its existing signed application
slot. The selector was `0x01001001` (RTC branch), STORE1 was `3774976`, and the
programmed MAC field was `29492`, exactly `STORE1 >> 7`. The MAC clock-enable
bit was set. The earlier diagnostic image still returned the fixed `44462`;
its STORE1 measurement was `3774682`.

Both the formatter/RX-recovery probe and three-cycle PHY guard shutdown/wakeup
probe passed after the clock change. RX smoke received eleven frames including
two OFDM frames; the lifetime probe received three beacons after wakeup.

The diagnostic baseline completed four traffic cycles (80/80 host, 78/80 gateway)
and failed association in cycle5 with parsed status2. The measured-clock image
completed three (60/60 host, 59/60 gateway) and hit the same association status in
cycle4. Neither run recorded a deauthentication frame. Both captures had zero
socket drops. These failures are retained: measured calibration is a configuration
correction, not a demonstrated packet-loss or reconnect fix.

Exact image/map/log hashes and probe results are in the
[device report](../network/clock-connection-validation.json). The following
[connection report](../network/CONNECTION-RESPONSE-VALIDATION.md) records the
subsequent host reproduction and device observation of a queued authentication
frame during association. That response-revalidation correction is independent
of this clock change; remaining gateway losses are still recorded separately.
