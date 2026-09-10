//! C3 MAC initialization translated from the reviewed `hal_mac.o` reference.
//!
//! Register transactions keep the order and 32-bit widths of the original.
//! The eight MAC helper bodies are included below; PHY remains external.
//! See docs/esp32c3/MAC-INIT.md for original instruction evidence and test limits.

#[inline(always)]
fn read(address: usize) -> u32 {
    #[cfg(test)]
    unsafe {
        return c3_test_read(address);
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
        c3_test_write(address, value);
    }
    #[cfg(not(test))]
    unsafe {
        (address as *mut u32).write_volatile(value)
    }
}

#[cfg(test)]
unsafe extern "C" {
    fn c3_test_read(address: usize) -> u32;
    fn c3_test_write(address: usize, value: u32);
}

#[inline(always)]
fn update(address: usize, keep: u32, set: u32) {
    write(address, (read(address) & keep) | set);
}

use helpers::*;
unsafe extern "C" {
    fn phy_disable_low_rate();
}

fn init_tx_rx() {
    update(0x60033c6c, u32::MAX, 0x8080a000);
    update(0x60033c6c, u32::MAX, 0x100);
    for interface in 0..4 {
        update(0x600330d8 + 4 * interface, u32::MAX, 0x40);
        update(0x600330d8 + 4 * interface, 0xffffffdf, 0);
    }
    update(0x60033c74, u32::MAX, 8);
    for interface in 0..4 {
        update(0x60033100 + 4 * interface, 0xffff, 0);
    }
    update(0x60033100, u32::MAX, 0x1000000);
    update(0x60033104, u32::MAX, 0x1000000);
    update(0x60033100, u32::MAX, 0x4000000);
    update(0x60033104, u32::MAX, 0x4000000);
    update(0x60033c6c, u32::MAX, 0x200);
    update(0x60033114, 0xffffff0f, 0);
    update(0x60033118, u32::MAX, 0x80000000);
    update(0x60033118, 0xf00fffff, 0x1b00000);
    update(0x60033c78, u32::MAX, 3);
    update(0x60033c10, 0xfffff000, 0xf0);
    update(0x60033c10, u32::MAX, 0x80000000);
    update(0x60033c10, u32::MAX, 0x40000000);
    update(0x60033c14, 0xfffff000, 0xf0);
    update(0x60033c18, 0xfffff000, 0xf0);
    update(0x60033c94, 0xffffff0f, 0x40);
    update(0x60033c54, u32::MAX, 0x7fff0000);
    update(0x60033c54, u32::MAX, 0x80000000);
    update(0x60033c88, 0xf0ffffff, 0);
    update(0x600332b8, u32::MAX, 2);
    update(0x60033084, 0x7fffffff, 0);
}

fn init_rx_buffers() {
    update(0x60033c5c, 0xfff00000, 0xe0000);
    update(0x60033c60, 0xfff00000, 0x80000);
    update(0x60033c64, 0x000fffff, 0x3fc00000);
    update(0x60033080, 0xffffff00, 0);
    // The Rust driver owns the DMA list and installs it after MAC initialization.
    write(0x60033088, 0);

    let filters = [
        [0x23006, 0x608, 0xffff],
        [0x23006, 0x808, 0xffff],
        [0x23006, 0x8e88, 0xffff],
        [0x2301c, 0x44004300, u32::MAX],
        [0x2301c, 0x43004400, u32::MAX],
        [0x23011, 1, 0xff],
    ];
    for (index, [config, value, mask]) in filters.into_iter().enumerate() {
        write(0x60033120 + index * 4, config);
        write(0x6003313c + index * 4, value);
        write(0x60033158 + index * 4, mask);
    }
    update(0x6003311c, u32::MAX, 0x3f00);
    update(0x6003311c, u32::MAX, 0x7e);
    update(0x6003309c, u32::MAX, 0x8000000);
}

/// Initialize the C3 MAC after power, clocks and PHY have been enabled.
///
/// The caller must own the MAC, hold RX disabled and install the ROM OS adapter.
pub(crate) unsafe fn init() {
    update(0x60033d14, u32::MAX, 2);
    while read(0x60033d14) & 1 == 0 {}
    write(0x60033c34, 0);
    write(0x60033c40, u32::MAX);
    init_tx_rx();
    for interface in 0..4 {
        let policy = 0x600330d8 + 4 * interface;
        update(policy, u32::MAX, 5);
        update(policy, 0xfffff6ff, 0);
        // The blob's hal_mac_rx_set_policy rejects interface 3.
        if interface < 3 {
            update(policy, 0xfffffeef, 0);
            update(0x60033024 + 8 * interface, 0xfffeffff, 0);
            update(0x60033064 + 8 * interface, 0xfffeffff, 0);
        }
    }
    init_rx_buffers();
    unsafe { hal_mac_rate_autoack_init() };
    unsafe { phy_disable_low_rate() };
    write(0x60033410, 0x90a0b);
    write(0x60033414, 0x50100);
    write(0x60033404, 0x90a0b);
    write(0x60033408, 0x50100);
    unsafe {
        hal_crypto_init();
        hal_attenna_init();
    }
    write(0x60033c34, 0x19a879e0);
    update(0x60033c6c, u32::MAX, 0x10000000);
    update(0x6003309c, 0xffffff00, 1);
    update(0x6003309c, 0xffff00ff, 0x200);
    update(0x6003309c, u32::MAX, 0x100000);
    unsafe {
        hal_timer_update_by_rtc(1, crate::ffi::slowclk_cal_get());
        hal_coex_pti_init();
        // Bluetooth coexistence is not active in this driver. The OS adapter's
        // event-3 and event-15 priority lookups leave the initialized zero bytes.
        hal_set_rx_active_pti(0);
        hal_set_rx_ack_pti(0);
        hal_set_wifi_default_pti(0);
    }
}

pub(crate) mod helpers {
    use super::{update, write};
    pub(crate) unsafe fn hal_crypto_init() {
        write(0x60033800, 0x30000);
        write(0x60033804, 0x30000);
        write(0x60033808, 0);
        write(0x6003380c, 0);
        write(0x60033810, 0);
        update(0x60033840, u32::MAX, 0x19);
    }

    pub(crate) unsafe fn hal_attenna_init() {
        // The original spelling is retained for comparison with the blob symbol.
        // Clear the antenna selection across all eight slots before changing mode.
        for slot in 0..8 {
            update(0x60034314 - slot * 0x4c, !7, 0);
        }
        for slot in 0..8 {
            let address = 0x60034314 - slot * 0x4c;
            // Keep these three transactions separate, including their intervening reads.
            update(address, !8, 0);
            update(address, u32::MAX, 0x20);
            update(address, !0x10, 0);
        }
        update(0x600332a8, !7, 0);
        update(0x600332a8, u32::MAX, 0x20);
    }

    pub(crate) unsafe fn hal_mac_rate_autoack_init() {
        write(0x60033418, 0);
        write(0x6003340c, 0x19191919);
    }

    pub(crate) unsafe fn hal_coex_pti_init() {
        update(0x60035084, u32::MAX, 2);
    }

    pub(crate) unsafe fn hal_set_rx_active_pti(priority: u32) {
        update(0x600332ac, !0xf, priority & 0xf);
    }

    pub(crate) unsafe fn hal_set_rx_ack_pti(priority: u32) {
        update(0x600332ac, !0xf0, (priority & 0xf) << 4);
    }

    pub(crate) unsafe fn hal_set_wifi_default_pti(priority: u32) {
        update(0x60035094, !0xf00, (priority & 0xf) << 8);
    }

    pub(crate) unsafe fn hal_timer_update_by_rtc(enable: u32, calibration: u32) {
        // C3 original instructions branch on the full a0 register.
        if enable != 0 {
            update(0x60035024, u32::MAX, 1 << 25);
            update(0x60035058, !0x3ffff, calibration & 0x3ffff);
        } else {
            update(0x60035024, !(1 << 25), 0);
        }
    }
}
