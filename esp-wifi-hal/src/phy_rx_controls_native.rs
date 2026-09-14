#[cfg(all(not(test), any(target_arch = "riscv32", target_arch = "xtensa")))]
mod native {
    use super::*;
    use core::ptr::{read_volatile, write_volatile};
    unsafe extern "C" {
        static mut phy_param: u8;
        static mut g_phyFuns: usize;
        fn ets_delay_us(microseconds: u32);
    }
    struct Hardware;
    impl Access for Hardware {
        #[inline(always)]
        unsafe fn parameter() -> usize {
            (&raw const phy_param) as usize
        }
        #[inline(always)]
        unsafe fn table_global() -> usize {
            (&raw const g_phyFuns) as usize
        }
        #[inline(always)]
        unsafe fn read(a: usize, width: usize) -> u32 {
            unsafe {
                match width {
                    1 => read_volatile(a as *const u8) as u32,
                    2 => read_volatile(a as *const u16) as u32,
                    4 => read_volatile(a as *const u32),
                    _ => unreachable!(),
                }
            }
        }
        #[inline(always)]
        unsafe fn write(a: usize, width: usize, value: u32) {
            unsafe {
                match width {
                    1 => write_volatile(a as *mut u8, value as u8),
                    2 => write_volatile(a as *mut u16, value as u16),
                    4 => write_volatile(a as *mut u32, value),
                    _ => unreachable!(),
                }
            }
        }
        #[inline(always)]
        unsafe fn delay(us: u32) {
            unsafe { ets_delay_us(us) }
        }
        #[inline(always)]
        unsafe fn callback(target: usize, argument: Option<usize>) {
            unsafe {
                if let Some(arg) = argument {
                    core::mem::transmute::<usize, unsafe extern "C" fn(usize)>(target)(arg);
                } else {
                    core::mem::transmute::<usize, unsafe extern "C" fn()>(target)();
                }
            }
        }
        #[inline(always)]
        unsafe fn local(p: *mut u16) -> usize {
            p as usize
        }
        #[inline(always)]
        unsafe fn trigger() {
            unsafe { __opensensor_rx_controls_trigger() }
        }
    }
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub unsafe extern "C" fn __opensensor_rx_controls_reset(enabled: u32) {
        unsafe { reset::<Hardware>(enabled) }
    }
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub unsafe extern "C" fn __opensensor_rx_controls_trigger() {
        unsafe { trigger::<Hardware>() }
    }
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub unsafe extern "C" fn __opensensor_rx_controls_estimate(mode: u32, samples: u32) {
        unsafe { estimate::<Hardware>(mode, samples) }
    }
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub unsafe extern "C" fn __opensensor_rx_controls_check() {
        unsafe { check::<Hardware>() }
    }
}
