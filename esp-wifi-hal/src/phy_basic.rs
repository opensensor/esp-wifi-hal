//! Remaining selected basic PHY helpers; ROM channel routing stays external.

pub(crate) trait Access {
    unsafe fn enter();
    unsafe fn exit();
    unsafe fn read_register(address: usize) -> u32;
    unsafe fn write_register(address: usize, value: u32);
    unsafe fn parameter(offset: usize) -> u8;
    unsafe fn power(value: i32);
}

#[inline(always)]
pub(crate) unsafe fn reset<A: Access>() {
    unsafe {
        A::enter();
        for address in [0x6000_e000, 0x6000_e004] {
            if A::read_register(address) & (1 << 25) != 0 {
                A::write_register(address, 1 << 26);
                while A::read_register(address) & (1 << 25) != 0 {}
            }
        }
        A::exit();
    }
}

#[inline(always)]
pub(crate) unsafe fn channel14<A: Access>(argument: u32) {
    #[cfg(esp32c3)]
    let enabled = argument == 1;
    #[cfg(esp32s3)]
    let enabled = argument as u8 == 1;
    unsafe {
        let previous = A::read_register(0x6001_c400);
        let value = if enabled {
            (previous & !0x6000) | 0x2000
        } else {
            previous | 0x6000
        };
        A::write_register(0x6001_c400, value);
        let power = A::parameter(if enabled { 0xe4 } else { 0x98 });
        A::power(power as i8 as i32);
    }
}

#[cfg(esp32s3)]
pub(crate) trait Calibration {
    unsafe fn read(&self, index: usize) -> u8;
}

#[cfg(esp32s3)]
#[inline(always)]
pub(crate) unsafe fn interpolate<C: Calibration>(data: &C, channel: u32) -> u32 {
    let index = channel.wrapping_sub(1) as u8;
    let value = unsafe {
        if index < 6 {
            let first = data.read(0);
            let second = data.read(1);
            first as i32 + (second as i8 as i32 - first as i8 as i32) * index as i32 / 5
        } else {
            let third = data.read(2);
            if index > 10 {
                third as i32 + 2
            } else {
                let second = data.read(1);
                second as i32 + (third as i8 as i32 - second as i8 as i32) * (index as i32 - 5) / 5
            }
        }
    };
    value as u8 as u32
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
        fn phy_i2c_enter_critical();
        fn phy_i2c_exit_critical();
        fn phy_set_most_tpw(value: i32);
    }
    pub(super) struct Native;
    impl Access for Native {
        #[inline(always)]
        unsafe fn enter() {
            unsafe { phy_i2c_enter_critical() }
        }
        #[inline(always)]
        unsafe fn exit() {
            unsafe { phy_i2c_exit_critical() }
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
        unsafe fn parameter(offset: usize) -> u8 {
            unsafe {
                (&raw const phy_param)
                    .cast::<u8>()
                    .add(offset)
                    .read_volatile()
            }
        }
        #[inline(always)]
        unsafe fn power(value: i32) {
            unsafe { phy_set_most_tpw(value) }
        }
    }
    #[cfg(esp32s3)]
    pub(super) struct Calibration(pub(super) *const u8);
    #[cfg(esp32s3)]
    impl super::Calibration for Calibration {
        #[inline(always)]
        unsafe fn read(&self, index: usize) -> u8 {
            unsafe { self.0.add(index).read_volatile() }
        }
    }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[esp_hal::ram]
unsafe extern "C" fn __opensensor_basic_reset() {
    unsafe { reset::<native::Native>() }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_basic_channel14(argument: u32) {
    unsafe { channel14::<native::Native>(argument) }
}

#[cfg(all(not(test), esp32s3))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_basic_interpolate(data: *const u8, channel: u32) -> u32 {
    unsafe { interpolate(&native::Calibration(data), channel) }
}
