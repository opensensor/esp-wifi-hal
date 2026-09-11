# Remaining PHY and ROM dependencies

The station driver has replaced the selected MAC member, low-rate PHY helper
and its direct AGC calls. It still depends on vendor PHY initialization,
calibration, channel selection and power tracking. This inventory distinguishes
those dependencies from ROM runtime helpers and the library's installed RAM
callbacks. It does not introduce a new PHY implementation or hardware result.

## Exact image scope

The [machine-readable inventory](phy-dependencies.json) records complete ELF,
map and archive hashes, member allocations, selected symbols and conservative
ROM-reference counts. Firmware and network settings remain private.

| Image | Evidence state at this audit | `libphy.a` allocated bytes / sections / members | `libprintf.a` allocated bytes |
| --- | --- | --- | --- |
| C3 `mac-retry-fixed-ten`, ELF `166e95834a7a…` | Built Retry correction; dedicated hardware run pending at audit time | 35,605 / 167 / 18 | 4,992 |
| S3 `sta-mac-sequence`, ELF `26834476784b…` | Tested FoA sequence-assignment image; also used unchanged for the traced A/B/A repeat | 33,250 / 166 / 18 | 4,738 |

These maps allocate no `libpp.a` input sections. Both use their chip's
`esp-wifi-sys` 0.2.0 archive. The PHY totals match the earlier tested helper
milestones; subsequent neighbor-response, FoA ownership/sequence and Retry
changes did not remove another PHY member. The C3 row is explicitly a build
inventory, not a claim that its new image has already passed device testing.

For allocation counting, parse the live linker input-section contributions:
GNU ld's memory-map portion on S3, or LLD's `In` entries on C3. Retain an input
range only if it lies completely within an ELF output section whose
`sh_flags` contains `SHF_ALLOC`. Exclude discarded, debug and other
non-allocated sections, and do not add linker padding. Sum input code and data
bytes; symbol lengths alone miss literals and tables. ROM contents are not
part of these totals.

This corrects an older S3 reporting error: the prior 11,981-byte `libprintf.a`
figure included 7,239 bytes of non-allocated `.debug_info` because that section's
map offset exceeded `0x100000`. The exact historical station images allocate
4,742 bytes instead. Their PHY allocations and hardware observations are
unchanged. The newer S3 image's 4,738 bytes belong to a different link and must
not be substituted into the old image records.

## Where the remaining calls enter

| Entry path | Remaining implementation and role |
| --- | --- |
| `LowLevelDriver::init` → `esp_phy::enable_phy` | Open Rust clock/lifetime management calls vendor `phy_bbpll_en_usb` and `register_chipv7_phy`; the latter owns RF initialization and calibration. The initial call has no saved calibration data and requests full calibration. |
| `LowLevelDriver::set_channel` → `chip_v7_set_chan(channel, 0)` | Vendor channel/PLL and gain work, plus calls through `g_phyFuns`. The Rust driver's extra AGC pair occurs outside this function and keeps the direct ROM contract. |
| `LowLevelDriver::run_power_control` → `tx_pwctrl_background(1, 0)` | Small vendor forwarding wrapper, then `ram_tx_pwctrl_background`; temperature reading, TX power tracking and conditional PLL tracking remain vendor work. |
| Last `esp_phy` guard dropped | Vendor `phy_dig_reg_backup`, `phy_close_rf`, and `phy_xpd_tsens`; backup and shutdown code remains linked. |
| Later `esp_phy` enable after calibration | Vendor `phy_wakeup_init` and digital-register restore. Station reconnect cycles keep the driver/PHY guard alive and do not establish full teardown/wakeup coverage. |

The open adapter is `esp-phy` 0.2.0 (`src/lib.rs`, calibration and reference-count
paths). Its source makes the lifetime branches explicit; a linked branch is
not evidence that a particular station test executed it.

The 18 allocated PHY members cover the following groups on both chips:

| Group | Allocated archive members |
| --- | --- |
| Entry points, state and initialization | `phy_api.o`, `phy_init.o`, `phy_basic.o`, `phy_feature.o` |
| Channel and analog clocks | `phy_hw_freq.o`, `phy_rfpll.o`, `phy_analog_cal.o` |
| Bus and register access | `phy_reg.o`, `phy_i2c.o`, `phy_pbus.o` |
| Receive and transmit calibration/gain | `phy_rx_cal.o`, `phy_rx_gain.o`, `phy_tx_cal.o`, `phy_tx_gain.o` |
| Tracking, temperature, measurement | `phy_track.o`, `phy_tsens.o`, `phy_pwdet.o`, `phy_debug.o` |

Member names describe the grouping; concrete call and register evidence is
still required before replacing any routine. Both images also allocate
`libprintf.a(printf.c.obj)` for PHY output/formatting. That is a separate
support-library dependency, not RF calibration code.

## Direct ROM versus installed RAM callbacks

`phy_get_romfunc_addr` retrieves the ROM function table, stores `g_phyFuns`,
patches selected slots and supplies `phy_param` to ROM. Names beginning
`rom1_` or `ram_` are not reliable location indicators: the C3
`rom1_disable_wifi_agc` is an allocated RAM body at `0x40382108` in the audited
image, not a ROM entry.

On S3, the initializer installs RAM temperature, power/gain, PLL, I2C, AGC,
PBUS and related callbacks. Examples include `ram_tsens_temp_read` at table
offset `0x258`, `ram_wifi_track_tx_power` at `0x28c`,
`ram_txpwr_cal_track` at `0x268`, and the AGC pair at `8` / `12`.
`ram_tx_pwctrl_background` invokes those temperature/tracking table slots,
then conditionally calls `rfpll_cap_track`.

C3 has a different table layout and a ROM-version branch. Its initializer
queries `chip726_phyrom_version_num`; one branch supplies selected ROM
entries, while the other installs additional RAM gain and calibration
callbacks. Both converge on common RAM callbacks, including the AGC pair at
`8` / `12` and `rom1_tsens_temp_read` at `0x27c`.
C3 `ram_tx_pwctrl_background` calls `rom1_tsens_temp_read` in RAM, then
**directly** calls `rom_wifi_track_tx_power` at ROM veneer `0x40001c2c`.
Conditional `ram2_rfpll_cap_track` and `rfcal_track` calls follow. The C3
and S3 tracking bodies are not interchangeable.

The driver's direct ROM AGC references are gone, but the internal RAM AGC
pair deliberately remains. Its `0x6001c034` accesses must not replace the
driver's reviewed `0x6001c038` operations; the prior S3 recovery experiment
demonstrated that call-context distinction.

The static audit resolves at least 36 distinct ROM targets in the S3 image
and 40 in the C3 image. These are **whole-firmware** lower bounds, including
memory, arithmetic, cache/runtime and print support. PHY-related examples
include `phy_get_romfuncs`, `rom_phy_param_addr`,
`rom_phy_dig_reg_backup`, `rom_phy_freq_mem_backup`, I2C access and
`ets_delay_us`; C3 also has direct references to ROM channel/gain/PLL routines.
Unresolved indirect/table calls are excluded, so these numbers are neither
the total ROM dependency count nor dynamic call counts. A defined absolute
ROM symbol without a call site is not counted as a dependency.

## Next bounded candidates

The highest-confidence small vendor wrapper is `tx_pwctrl_background`:

- C3: a two-byte tail jump to `ram_tx_pwctrl_background`.
- S3: a 14-byte body narrowing both arguments to eight bits and forwarding
  them to that same-named RAM routine.

The driver already passes `(1, 0)`. A source wrapper can preserve that ABI and
call order without reproducing analog behavior or changing callback tables.
Validate forwarding against the original instructions, inspect both compiled
ABIs, prove the old wrapper section is discarded and the RAM callee retained,
then run the same station/RX and lifetime checks. This is only a small wrapper
replacement: the 122-byte C3 and 78-byte S3 RAM tracking bodies and their
calibration dependencies remain. Any code-size reduction must be measured,
not inferred from the wrapper's body length.

`phy_bbpll_en_usb` is another small, directly evidenced candidate. It performs
one byte store to `phy_param + 0x323` on C3 or `phy_param + 0x2a6` on S3.
Its body is 10 / 14 bytes respectively; S3 also allocates a four-byte literal.
Replacing it requires a change at the `esp-phy` call site or a carefully
defined symbol integration, pinning this private vendor layout and verifying
that adjacent bytes remain untouched. It does not replace PLL setup or USB
clock calibration. Validate both argument values, field bounds, initialization
ordering and USB/PHY initialization on each chip before adoption.

A useful separate source correction is still pending on S3:
`ffi::slowclk_cal_get` returns fixed `44462` (`0xadae`), confirmed in the
audited station instructions. The
[ESP-IDF S3 wrapper](https://github.com/espressif/esp-idf/blob/67c1de1eebe095d554d281952fde63c16ee2dca0/components/esp_coex/esp32s3/esp_coex_adapter.c)
instead tests XTAL-selection bit 26 at `0x600c002c`, returning Q12 `4096` for
divided XTAL or the measured RTC STORE1 value at `0x60008054` shifted right
by seven. C3 already follows its corresponding contract, whose select register
is at `0x600c0024`, not the S3 address. The S3 follow-up should compare original
IDF instruction traces for both branches, check volatile access/barriers and
the board's post-initialization calibration, then perform controlled device
testing. It is a configuration-correctness candidate, not further blob removal
or an established explanation of lost packets.

None of these candidates justifies replacing `register_chipv7_phy`, channel
tuning, calibration algorithms or the callback installer wholesale. Periodic
power-control timing and the still-unexplained receive losses are separate
investigations; this inventory changes neither RF settings nor scheduling.
