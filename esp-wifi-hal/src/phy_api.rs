//! Remaining C3/S3 PHY API entry points, with retained RF helpers and cadence.
//! Access widths and callback order follow the pinned original instructions.

pub(crate) trait Access {
    type Table: Copy;
    type Function: Copy;
    unsafe fn wakeup();
    unsafe fn close();
    unsafe fn frequency_init();
    #[cfg(esp32c3)]
    unsafe fn measure();
    unsafe fn read8(offset: usize) -> u8;
    unsafe fn read32(offset: usize) -> u32;
    unsafe fn write32(offset: usize, value: u32);
    #[cfg(esp32c3)]
    unsafe fn write8(offset: usize, value: u8);
    unsafe fn table() -> Self::Table;
    unsafe fn slot(table: Self::Table, offset: usize) -> Self::Function;
    unsafe fn channel(function: Self::Function, channel: u8);
    #[cfg(esp32s3)]
    unsafe fn read_register(address: usize) -> u32;
    #[cfg(esp32s3)]
    unsafe fn write_register(address: usize, value: u32);
}

#[inline(always)]
pub(crate) unsafe fn wakeup<A: Access>() {
    unsafe {
        A::wakeup();
        if A::read32(0x120) & 0x20 == 0 {
            A::frequency_init();
            let table = A::table();
            let channel = A::read8(0x1f2);
            #[cfg(esp32c3)]
            let function = A::slot(table, 0xd8);
            #[cfg(esp32s3)]
            let function = A::slot(table, 0xcc);
            A::channel(function, channel);
            // A helper can change other bits: preserve the fresh word.
            let flags = A::read32(0x120);
            A::write32(0x120, flags | 0x20);
        }
    }
}

#[inline(always)]
pub(crate) unsafe fn close<A: Access>() {
    unsafe {
        #[cfg(esp32c3)]
        if A::read8(0x31f) == 0 {
            A::measure();
        }
        A::close();
        #[cfg(esp32c3)]
        A::write8(0x320, 1);
    }
}

#[inline(always)]
pub(crate) const fn calibration_version() -> u32 {
    #[cfg(esp32c3)]
    {
        0x4d0
    }
    #[cfg(esp32s3)]
    {
        0x2c7
    }
}

#[cfg(esp32s3)]
#[inline(always)]
pub(crate) unsafe fn set_tx_seed<A: Access>(seed: u32) {
    unsafe {
        let previous = A::read_register(0x6001_c400);
        A::write_register(0x6001_c400, (previous & !0x7f) | (seed & 0x7f));
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
        fn ram1_phy_wakeup_init();
        #[cfg(esp32c3)]
        fn ram1_phy_close_rf();
        #[cfg(esp32c3)]
        fn rom1_tsens_temp_read() -> u32;
        #[cfg(esp32s3)]
        fn ram_phy_wakeup_init();
        #[cfg(esp32s3)]
        fn ram_phy_close_rf();
        fn get_rf_freq_init();
    }
    pub(super) struct Native;
    impl Access for Native {
        type Table = *const u8;
        type Function = usize;
        #[inline(always)]
        unsafe fn wakeup() {
            #[cfg(esp32c3)]
            unsafe {
                ram1_phy_wakeup_init()
            }
            #[cfg(esp32s3)]
            unsafe {
                ram_phy_wakeup_init()
            }
        }
        #[inline(always)]
        unsafe fn close() {
            #[cfg(esp32c3)]
            unsafe {
                ram1_phy_close_rf()
            }
            #[cfg(esp32s3)]
            unsafe {
                ram_phy_close_rf()
            }
        }
        #[inline(always)]
        unsafe fn frequency_init() {
            unsafe { get_rf_freq_init() }
        }
        #[cfg(esp32c3)]
        #[inline(always)]
        unsafe fn measure() {
            unsafe {
                rom1_tsens_temp_read();
            }
        }
        #[inline(always)]
        unsafe fn read8(offset: usize) -> u8 {
            unsafe {
                (&raw const phy_param)
                    .cast::<u8>()
                    .add(offset)
                    .read_volatile()
            }
        }
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
        unsafe fn write32(offset: usize, value: u32) {
            unsafe {
                (&raw mut phy_param)
                    .cast::<u8>()
                    .add(offset)
                    .cast::<u32>()
                    .write_volatile(value)
            }
        }
        #[cfg(esp32c3)]
        #[inline(always)]
        unsafe fn write8(offset: usize, value: u8) {
            unsafe {
                (&raw mut phy_param)
                    .cast::<u8>()
                    .add(offset)
                    .write_volatile(value)
            }
        }
        #[inline(always)]
        unsafe fn table() -> Self::Table {
            unsafe { (&raw const g_phyFuns).read_volatile() }
        }
        #[inline(always)]
        unsafe fn slot(table: Self::Table, offset: usize) -> Self::Function {
            unsafe { table.add(offset).cast::<usize>().read_volatile() }
        }
        #[inline(always)]
        unsafe fn channel(function: Self::Function, channel: u8) {
            unsafe { core::mem::transmute::<usize, unsafe extern "C" fn(u8)>(function)(channel) }
        }
        #[cfg(esp32s3)]
        #[inline(always)]
        unsafe fn read_register(address: usize) -> u32 {
            unsafe { (address as *const u32).read_volatile() }
        }
        #[cfg(esp32s3)]
        #[inline(always)]
        unsafe fn write_register(address: usize, value: u32) {
            unsafe { (address as *mut u32).write_volatile(value) }
        }
    }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[esp_hal::ram]
unsafe extern "C" fn __opensensor_api_wakeup() {
    unsafe { wakeup::<native::Native>() }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[esp_hal::ram]
unsafe extern "C" fn __opensensor_api_close() {
    unsafe { close::<native::Native>() }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
extern "C" fn __opensensor_api_calibration_version() -> u32 {
    calibration_version()
}
#[cfg(all(not(test), esp32s3))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_api_tx_seed(seed: u32) {
    unsafe { set_tx_seed::<native::Native>(seed) }
}
