//! Feature helpers, retaining the original ROM backup and gain dependencies.

pub(crate) trait Access {
    unsafe fn parameter(offset: usize) -> u8;
    unsafe fn set_parameter(offset: usize, value: u8);
    unsafe fn table() -> usize;
    unsafe fn callback(table: usize, offset: usize) -> usize;
    unsafe fn call(target: usize, args: [u32; 4]);
    unsafe fn gain(channel: u32);
    unsafe fn read_register(address: usize) -> u32;
    unsafe fn write_register(address: usize, value: u32);
    unsafe fn backup(kind: u32, mode: u32, buffer: usize) -> u32;
}

#[inline(always)]
pub(crate) unsafe fn backup<A: Access>(kind: u32, mode: u32, buffer: usize) -> u32 {
    #[cfg(esp32s3)]
    let mode = mode as u8 as u32;
    unsafe { A::backup(kind, mode, buffer) }
}

#[inline(always)]
pub(crate) unsafe fn power<A: Access>(value: u32) {
    unsafe {
        #[cfg(esp32s3)]
        let table = A::table();
        A::set_parameter(0x98, value as u8);
        #[cfg(esp32s3)]
        let callback = A::callback(table, 0x264);
        let channel = A::parameter(0x1f2) as u32;
        #[cfg(esp32c3)]
        A::gain(channel);
        #[cfg(esp32s3)]
        A::call(callback, [channel, 0, 0, 0]);
    }
}

#[inline(always)]
pub(crate) unsafe fn mode<A: Access>(enabled: u32, narrow: u32) {
    #[cfg(esp32s3)]
    let (enabled, narrow) = (enabled as u8 as u32, narrow as u8 as u32);
    #[cfg(esp32c3)]
    const SLOT: usize = 0x1b4;
    #[cfg(esp32s3)]
    const SLOT: usize = 0x190;
    #[cfg(esp32c3)]
    const HOST: u32 = 1;
    #[cfg(esp32s3)]
    const HOST: u32 = 0;
    unsafe {
        #[cfg(esp32c3)]
        let table = A::table();
        A::set_parameter(0xef, enabled as u8);
        A::set_parameter(0xf0, narrow as u8);
        #[cfg(esp32c3)]
        let first = A::callback(table, SLOT);

        let previous = A::read_register(0x6002_600c);
        let selection = if enabled == 0 {
            0
        } else if narrow == 0 {
            4
        } else {
            5
        };
        A::write_register(0x6002_600c, (previous & !0x1c) | (selection << 2));
        let previous = A::read_register(0x6001_c030);
        A::write_register(
            0x6001_c030,
            if enabled == 0 {
                previous | 0x20
            } else {
                previous & !0x20
            },
        );
        let computed = if enabled != 0 {
            let parameter = A::parameter(0x166) as u32;
            (((parameter + 56) * 103) / if narrow == 0 { 100 } else { 50 } - 8).min(63)
        } else {
            0
        };

        for (index, register) in [4, 5, 12, 13, 6, 7, 14, 15].into_iter().enumerate() {
            // C3 preloads its first callback before touching MMIO. Subsequent
            // table loads and disabled-mode parameter reads follow each call.
            #[cfg(esp32c3)]
            let table = if index == 0 { None } else { Some(A::table()) };
            #[cfg(esp32s3)]
            let table = A::table();
            let value = if enabled != 0 {
                computed
            } else {
                A::parameter(if index < 4 { 0x167 } else { 0x168 }) as u32
            };
            #[cfg(esp32c3)]
            let target = match table {
                None => first,
                Some(table) => A::callback(table, SLOT),
            };
            #[cfg(esp32s3)]
            let target = A::callback(table, SLOT);
            A::call(target, [103, HOST, register, value]);
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
        fn rom_phy_dig_reg_backup(mode: u32, buffer: *mut u32) -> u32;
        fn rom_phy_freq_mem_backup(mode: u32, buffer: *mut u32);
        #[cfg(esp32c3)]
        fn ram1_wifi_set_tx_gain(channel: u32, zero: u32);
    }
    pub(super) struct Native;
    impl Access for Native {
        #[inline(always)]
        unsafe fn parameter(offset: usize) -> u8 {
            unsafe {
                (&raw const phy_param)
                    .cast::<u8>()
                    .add(offset)
                    .read_volatile()
            }
        }
        #[inline(always)]
        unsafe fn set_parameter(offset: usize, value: u8) {
            unsafe {
                (&raw mut phy_param)
                    .cast::<u8>()
                    .add(offset)
                    .write_volatile(value)
            }
        }
        #[inline(always)]
        unsafe fn table() -> usize {
            unsafe { (&raw const g_phyFuns).read_volatile() as usize }
        }
        #[inline(always)]
        unsafe fn callback(table: usize, offset: usize) -> usize {
            unsafe { ((table + offset) as *const usize).read_volatile() }
        }
        #[inline(always)]
        unsafe fn call(target: usize, args: [u32; 4]) {
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32, u32, u32)>(target)(
                    args[0], args[1], args[2], args[3],
                )
            }
        }
        #[inline(always)]
        unsafe fn gain(channel: u32) {
            #[cfg(esp32c3)]
            unsafe {
                ram1_wifi_set_tx_gain(channel, 0)
            }
            #[cfg(esp32s3)]
            let _ = channel;
        }
        #[inline(always)]
        unsafe fn read_register(address: usize) -> u32 {
            unsafe { (address as *const u32).read_volatile() }
        }
        #[inline(always)]
        unsafe fn write_register(address: usize, value: u32) {
            unsafe { (address as *mut u32).write_volatile(value) }
        }
        #[inline(always)]
        unsafe fn backup(kind: u32, mode: u32, buffer: usize) -> u32 {
            unsafe {
                if kind == 0 {
                    rom_phy_dig_reg_backup(mode, buffer as *mut u32)
                } else {
                    rom_phy_freq_mem_backup(mode, buffer as *mut u32);
                    0
                }
            }
        }
    }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[esp_hal::ram]
unsafe extern "C" fn __opensensor_feature_dig(mode: u32, buffer: *mut u32) -> u32 {
    unsafe { backup::<native::Native>(0, mode, buffer as usize) }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[esp_hal::ram]
unsafe extern "C" fn __opensensor_feature_freq(mode: u32, buffer: *mut u32) {
    unsafe {
        backup::<native::Native>(1, mode, buffer as usize);
    }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_feature_power(value: u32) {
    unsafe { power::<native::Native>(value) }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_feature_mode(enabled: u32, narrow: u32) {
    unsafe { mode::<native::Native>(enabled, narrow) }
}
