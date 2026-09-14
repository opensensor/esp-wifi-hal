#[cfg(all(not(test), any(target_arch = "riscv32", target_arch = "xtensa")))]
mod native {
    use super::*;
    use core::ptr::{read_volatile, write_volatile};
    unsafe extern "C" {
        static mut g_phyFuns: usize;
        fn start_tx_tone_step(enable: u32, frequency: u32, gain: u32, a: u32, b: u32, c: u32);
        fn stop_tx_tone(enable: u32);
        fn rxiq_cover_mg_mp(mode: u32, magnitude: usize, phase: usize, logging: u32);
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
        unsafe fn start(f: u32, g: u32) {
            unsafe { start_tx_tone_step(1, f, g, 0, 0, 0) }
        }
        #[inline(always)]
        unsafe fn stop() {
            unsafe { stop_tx_tone(1) }
        }
        #[inline(always)]
        unsafe fn correct(m: u32, a: usize, b: usize, l: u32) {
            unsafe { rxiq_cover_mg_mp(m, a, b, l) }
        }
        #[inline(always)]
        unsafe fn log(i: u32, m: i32, p: i32) {
            unsafe { phy_printf(c"%d_%d_%d\n".as_ptr().cast(), i, m, p) }
        }
        #[inline(always)]
        unsafe fn table_global() -> usize {
            (&raw const g_phyFuns) as usize
        }
        #[inline(always)]
        unsafe fn difference(t: usize, v: i32) -> i32 {
            unsafe { core::mem::transmute::<usize, unsafe extern "C" fn(i32) -> i32>(t)(v) }
        }
        #[inline(always)]
        unsafe fn local(_: u32, p: *mut u8) -> usize {
            p as usize
        }
        #[inline(always)]
        unsafe fn sample(m: u32, f: u32, g: u32, p: usize, l: u32) {
            unsafe { __opensensor_rf_iq_sample(m, f, g, p, l) }
        }
    }
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub unsafe extern "C" fn __opensensor_rf_iq_sample(m: u32, f: u32, g: u32, p: usize, l: u32) {
        unsafe { sample::<Hardware>(m, f, g, p, l) }
    }
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub unsafe extern "C" fn __opensensor_rf_iq_collect(f: u32, g: u32, l: u32) -> u32 {
        unsafe { collect::<Hardware>(f, g, l) }
    }
}
