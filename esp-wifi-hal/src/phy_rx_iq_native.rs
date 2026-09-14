#[cfg(all(not(test), any(target_arch = "riscv32", target_arch = "xtensa")))]
mod native {
    use super::*;
    use core::ptr::{read_volatile, write_volatile};
    unsafe extern "C" {
        static mut g_phyFuns: usize;
        fn __divdi3(numerator: i64, denominator: i64) -> i64;
        fn rxiq_set_reg(coefficient: i32, mode: u32) -> u32;
        fn phy_printf(format: *const u8, ...);
    }
    struct Hardware;
    impl Access for Hardware {
        #[inline(always)]
        unsafe fn read(a: usize, w: usize) -> u32 {
            unsafe {
                match w {
                    1 => read_volatile(a as *const u8) as u32,
                    4 => read_volatile(a as *const u32),
                    _ => unreachable!(),
                }
            }
        }
        #[inline(always)]
        unsafe fn write(a: usize, w: usize, v: u32) {
            unsafe {
                match w {
                    1 => write_volatile(a as *mut u8, v as u8),
                    4 => write_volatile(a as *mut u32, v),
                    _ => unreachable!(),
                }
            }
        }
        #[inline(always)]
        unsafe fn divide(n: i64, d: i64) -> i64 {
            unsafe { __divdi3(n, d) }
        }
        #[inline(always)]
        unsafe fn log(s: i32, m: i32, p: i32) {
            unsafe { phy_printf(c"%d, %d-%d, ".as_ptr().cast(), s, m, p) }
        }
        #[inline(always)]
        unsafe fn set(c: i32, m: u32) -> u32 {
            unsafe { rxiq_set_reg(c, m) }
        }
        #[inline(always)]
        unsafe fn table_global() -> usize {
            (&raw const g_phyFuns) as usize
        }
        #[inline(always)]
        unsafe fn callback(target: usize, samples: Option<u32>) {
            unsafe {
                if let Some(s) = samples {
                    core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32)>(target)(1, s)
                } else {
                    core::mem::transmute::<usize, unsafe extern "C" fn()>(target)()
                }
            }
        }
        #[inline(always)]
        unsafe fn local(p: *mut u8) -> usize {
            p as usize
        }
        #[inline(always)]
        unsafe fn measure(m: u32, p: usize, l: u32) {
            unsafe { __opensensor_rx_iq_mismatch(m, p, l) }
        }
    }
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub unsafe extern "C" fn __opensensor_rx_iq_mismatch(m: u32, p: usize, l: u32) {
        unsafe { mismatch::<Hardware>(m, p, l) }
    }
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub unsafe extern "C" fn __opensensor_rx_iq_correct(m: u32, a: usize, b: usize, l: u32) {
        unsafe { correct::<Hardware>(m, a, b, l) }
    }
}
