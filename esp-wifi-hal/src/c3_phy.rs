//! Bounded C3 PHY controls reviewed against their existing vendor/ROM call targets.
//!
//! These functions require initialized PHY clocks and exclusive MAC/PHY access.
//! RF calibration, channel tuning and power tracking remain external.

#[inline(always)]
fn read(address: usize) -> u32 {
    #[cfg(test)]
    unsafe {
        c3_phy_test_read(address)
    }
    #[cfg(not(test))]
    unsafe {
        (address as *const u32).read_volatile()
    }
}

#[inline(always)]
fn write(address: usize, value: u32) {
    #[cfg(test)]
    unsafe {
        c3_phy_test_write(address, value);
    }
    #[cfg(not(test))]
    unsafe {
        (address as *mut u32).write_volatile(value);
    }
}

#[cfg(test)]
unsafe extern "C" {
    fn c3_phy_test_read(address: usize) -> u32;
    fn c3_phy_test_write(address: usize, value: u32);
}

#[inline(always)]
fn update(address: usize, keep: u32, set: u32) {
    write(address, (read(address) & keep) | set);
}

pub(crate) unsafe fn disable_low_rate() {
    // Keep both read/modify/write operations at 0x6001c860 separate.
    update(0x6001c860, !0x400, 0);
    update(0x6001c860, !0x800, 0);
    update(0x6001c87c, !0x800, 0);
}

pub(crate) unsafe fn disable_wifi_agc() {
    update(0x6001c01c, 0xff00ffff, 0x007f0000);
    // Preserve the driver's direct ROM contract. Internal libphy table
    // callbacks use 0x6001c034 and run in a different calling context.
    update(0x6001c038, u32::MAX, 0x80);
    update(0x6001c080, u32::MAX, 1);
}

pub(crate) unsafe fn enable_wifi_agc() {
    update(0x6001c080, !1, 0);
    update(0x6001c01c, 0xff00ffff, 0x00200000);
    update(0x6001c038, u32::MAX, 0x80);
}

/// Wi-Fi light-sleep clock period in Q12 microseconds, matching IDF's C3
/// esp_coex_common_clk_slowclk_cal_get_wrapper.
pub(crate) fn slowclk_cal_get() -> u32 {
    const XTAL_SELECTED: u32 = 1 << 26;
    if read(0x600c0024) & XTAL_SELECTED != 0 {
        // The modem's divided XTAL clock is 1 MHz: one microsecond in Q12.
        1 << 12
    } else {
        // esp-hal calibrates the selected RTC slow clock into STORE1 as
        // Q19 microseconds. The modem register uses twelve fractional bits.
        read(0x60008054) >> 7
    }
}
