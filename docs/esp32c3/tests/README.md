# C3 MAC and PHY transaction tests

The checked-in traces cover the complete Rust C3 MAC initialization
and eight additional MAC helper bodies. They were derived by bounded
interpretation of actual RV32IMC instructions from two separately linked vendor
baselines: ESP-IDF 5.4 and esp-wifi-sys-esp32c3 0.2.0. The archives differ
bytewise, but all 260 exercised instruction traces agree. The Rust implementation
produced the same ordered 32-bit MMIO transactions and the modeled PHY/clock
callback events.

Run from the repository root:

```sh
sh docs/esp32c3/tests/run-tests.sh
```

The test uses stable Rust and the checked-in trace data. Neither the private
reconstruction framework nor a model, cross compiler, SDK or board is required.

There are 260 cases. Four initial register patterns each exercise full
initialization, four fixed helpers, three priority helpers with eight input
values, and the RTC helper with six enable values and six calibration values.
The test compares every read and write in order, including antenna's two passes
and separate read/modify/write operations. It checks C3's RX descriptor range
values and its full-register RTC enable branch, including enable=256.

The oracle is a small instruction interpreter with explicit external-call
stubs, not a CPU, DMA engine or radio emulator. Unknown instructions fail. MMIO
is modeled as ordinary 32-bit registers; ready status is preset, the initial RX
descriptor base is zero, the clock callback returns a fixed value and Bluetooth
coexistence remains disabled. These traces do not validate interrupt timing,
hardware side effects, PHY behavior, MMIO bus ordering, Bluetooth scheduling,
power transitions or device reliability. The original initialization does not
contain explicit RISC-V FENCE instructions; this test does not establish whether
additional synchronization is needed outside the observed path.

`trace-evidence.json` records the baseline ELF and archive/member hashes,
function addresses, audited Rust source hash, oracle hash and trace file hash.
The addresses identify those analysis inputs, not fixed ROM entry points.

To regenerate independently, obtain matching vendor inputs, extract the named
functions with GNU RISC-V objdump, and interpret or instrument their integer
instructions with the documented register seeds and external-call assumptions.
Preserve the exact access widths and transaction order; do not regenerate
expected traces by running the Rust implementation being tested. Compare the
two original baselines before accepting new expected data. Full baseline
firmware, credentials and private harness code are not included here.

## PHY controls and slow-clock callback

The same runner also compiles `test_c3_phy.rs`, which imports the actual Rust PHY
module and compares it with `phy-traces.txt`. Its 48 cases consist of 16 PHY
cases (four initial register patterns across three controls and one combined
AGC cycle) and 32 clock cases (four source-register values by eight calibration
values). The observed C3 calibration is included. Clock cases check both the
return value and which registers are read.

The PHY oracle executes `phy_disable_low_rate` from the linked
esp-wifi-sys-esp32c3 0.2.0 baseline, plus `rom_disable_wifi_agc` and
`rom_enable_wifi_agc` from the C3 ROM ELF. The
clock oracle executes the stock ESP-IDF 5.4
`esp_coex_common_clk_slowclk_cal_get_wrapper` and `esp_clk_slowclk_cal_get` bodies.
`../phy-validation.json` records their input hashes and addresses. The original
MAC tests keep the low-rate PHY call mocked as a boundary event; the new PHY
tests independently exercise that replacement body.

Each trace starts with `case SEED FUNCTION [CLOCK_FLAGS RTC_CALIBRATION]`.
Following `r` and `w` rows record address and value in decimal; a `v 0 VALUE`
row records the clock return. To regenerate, execute the named original
instructions with these seeds and arguments, preserving their ordered 32-bit
transactions. The same bounded register-model limitations described above
apply. Matching these traces alone does not validate radio or sleep behavior.
