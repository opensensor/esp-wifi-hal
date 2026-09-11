//! C3/S3 tracking dispatcher; analog helpers and initialized vendor state remain.
//! See docs/network/PHY-POWER-CONTROL.md for the original instruction contract.

// Static dispatch permits host tests to observe the exact production access
// order. Native is inlined; no runtime trait object or alternate RF policy exists.
pub(crate) trait Access {
    unsafe fn read8(offset: usize) -> u8;
    #[cfg(esp32s3)]
    unsafe fn read32(offset: usize) -> u32;
    unsafe fn enter(slot: usize) -> u32;
    unsafe fn exit(slot: usize, token: u32);
    #[cfg(esp32s3)]
    unsafe fn table_temperature(slot: usize);
    #[cfg(esp32s3)]
    unsafe fn table_power(slot: usize, enabled: u8, mode: u8);
    #[cfg(esp32c3)]
    unsafe fn temperature();
    #[cfg(esp32c3)]
    unsafe fn power(enabled: u8, mode: u8);
    unsafe fn pll(value: u8);
    #[cfg(esp32c3)]
    unsafe fn rfcal(value: u8, threshold: u8);
}

/// Requires initialized vendor state and the caller's original PHY exclusion.
#[inline(always)]
pub(crate) unsafe fn dispatch<A: Access>(enabled: u8, mode: u8) {
    unsafe {
        #[cfg(esp32c3)]
        {
            let token = A::enter(0x184);
            let first = A::read8(0x320);
            let second = A::read8(0x31f);
            if first | second == 0 {
                A::temperature();
                A::power(enabled, mode);
                if A::read8(0x09c) != 0 {
                    A::pll(A::read8(0x09b));
                }
                // Helpers may change these fields: preserve both fresh reads.
                if A::read8(0x216) != 0 {
                    A::rfcal(A::read8(0x09b), 20);
                }
            }
            A::exit(0x188, token);
        }
        #[cfg(esp32s3)]
        {
            let token = A::enter(0x160);
            if A::read32(0x2a0) & 0xffff0000 == 0 {
                A::table_temperature(0x258);
                A::table_power(0x28c, enabled, mode);
                if A::read8(0x09c) != 0 {
                    A::pll(A::read8(0x09b));
                }
            }
            A::exit(0x164, token);
        }
    }
}

#[cfg(not(test))]
mod native {
    use super::Access;
    #[cfg(esp32c3)]
    const PARAM_SIZE: usize = 848;
    #[cfg(esp32s3)]
    const PARAM_SIZE: usize = 740;
    unsafe extern "C" {
        static mut phy_param: [u8; PARAM_SIZE];
        static mut g_phyFuns: *const u8;
        #[cfg(esp32c3)]
        fn rom1_tsens_temp_read();
        #[cfg(esp32c3)]
        fn ram2_rfpll_cap_track(value: u8);
        #[cfg(esp32c3)]
        fn rfcal_track(value: u8, threshold: u8);
        #[cfg(esp32s3)]
        fn rfpll_cap_track(value: u8);
    }
    // This is the direct C3 ROM veneer used by the original dispatcher, not
    // the similarly named RAM callback installed in the runtime table.
    #[cfg(esp32c3)]
    const ROM_WIFI_TRACK_TX_POWER: usize = 0x40001c2c;

    #[inline(always)]
    unsafe fn table_entry(slot: usize) -> usize {
        unsafe {
            // Reload g_phyFuns before every call, including exit. Helpers are
            // allowed to replace the table. Never hold a Rust reference to it.
            let table = (&raw const g_phyFuns).read_volatile();
            table.add(slot).cast::<usize>().read_volatile()
        }
    }
    pub(super) struct Native;
    impl Access for Native {
        #[inline(always)]
        unsafe fn read8(offset: usize) -> u8 {
            unsafe {
                (&raw const phy_param)
                    .cast::<u8>()
                    .add(offset)
                    .read_volatile()
            }
        }
        #[cfg(esp32s3)]
        #[inline(always)]
        unsafe fn read32(offset: usize) -> u32 {
            unsafe {
                (&raw const phy_param)
                    .cast::<u8>()
                    .add(offset)
                    .cast::<u32>()
                    .read_volatile()
            }
        }
        #[inline(always)]
        unsafe fn enter(slot: usize) -> u32 {
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn() -> u32>(table_entry(slot))()
            }
        }
        #[inline(always)]
        unsafe fn exit(slot: usize, token: u32) {
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u32)>(table_entry(slot))(token)
            }
        }
        #[cfg(esp32s3)]
        #[inline(always)]
        unsafe fn table_temperature(slot: usize) {
            unsafe { core::mem::transmute::<usize, unsafe extern "C" fn()>(table_entry(slot))() }
        }
        #[cfg(esp32s3)]
        #[inline(always)]
        unsafe fn table_power(slot: usize, enabled: u8, mode: u8) {
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u8, u8)>(table_entry(slot))(
                    enabled, mode,
                )
            }
        }
        #[cfg(esp32c3)]
        #[inline(always)]
        unsafe fn temperature() {
            unsafe { rom1_tsens_temp_read() }
        }
        #[cfg(esp32c3)]
        #[inline(always)]
        unsafe fn power(enabled: u8, mode: u8) {
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u8, u8)>(ROM_WIFI_TRACK_TX_POWER)(
                    enabled, mode,
                )
            }
        }
        #[inline(always)]
        unsafe fn pll(value: u8) {
            #[cfg(esp32c3)]
            unsafe {
                ram2_rfpll_cap_track(value)
            }
            #[cfg(esp32s3)]
            unsafe {
                rfpll_cap_track(value)
            }
        }
        #[cfg(esp32c3)]
        #[inline(always)]
        unsafe fn rfcal(value: u8, threshold: u8) {
            unsafe { rfcal_track(value, threshold) }
        }
    }
}

#[cfg(not(test))]
#[inline(never)]
pub(crate) unsafe fn tx_pwctrl_background(enabled: u8, mode: u8) {
    unsafe { dispatch::<native::Native>(enabled, mode) }
}
