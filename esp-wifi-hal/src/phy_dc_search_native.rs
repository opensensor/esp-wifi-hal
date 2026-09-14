#[cfg(all(not(test), any(target_arch = "riscv32", target_arch = "xtensa")))]
mod native {
    use super::*;
    use core::ptr::{read_volatile, write_volatile};
    unsafe extern "C" {
        static mut g_phyFuns: usize;
        fn ets_delay_us(value: u32);
        fn phy_printf(format: *const u8, ...);
        fn __opensensor_rx_dc_minimum(samples: u32, unused: u32, output: usize);
    }
    #[unsafe(no_mangle)]
    static __opensensor_dc_search_coarse: [u8; 6] = [80, 71, 63, 56, 50, 44];
    struct Hardware;
    impl Access for Hardware {
        #[inline(always)]
        unsafe fn read(a: usize, w: usize) -> u32 {
            unsafe {
                match w {
                    1 => read_volatile(a as *const u8) as u32,
                    2 => read_volatile(a as *const u16) as u32,
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
                    2 => write_volatile(a as *mut u16, v as u16),
                    4 => write_volatile(a as *mut u32, v),
                    _ => unreachable!(),
                }
            }
        }
        #[inline(always)]
        unsafe fn table_global() -> usize {
            (&raw const g_phyFuns) as usize
        }
        #[inline(always)]
        unsafe fn coarse(index: u32) -> u32 {
            // The private calibration ABI supplies indices 0..5. No adjacent
            // vendor data is treated as an extension of this six-byte table.
            unsafe {
                read_volatile(
                    (&raw const __opensensor_dc_search_coarse)
                        .cast::<u8>()
                        .add(index as usize),
                ) as u32
            }
        }
        #[inline(always)]
        unsafe fn local(p: *mut u32, _: usize) -> usize {
            p as usize
        }
        #[inline(always)]
        unsafe fn pbus_read(t: usize, block: u32, bank: u32) -> u32 {
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32) -> u32>(t)(block, bank)
            }
        }
        #[inline(always)]
        unsafe fn force(t: usize, block: u32, bank: u32, value: u32) {
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32, u32)>(t)(
                    block, bank, value,
                )
            }
        }
        #[inline(always)]
        unsafe fn estimate(t: usize, samples: u32, output: usize) {
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32, usize)>(t)(
                    1, samples, output,
                )
            }
        }
        #[inline(always)]
        unsafe fn difference(t: usize, value: i32) -> i32 {
            unsafe { core::mem::transmute::<usize, unsafe extern "C" fn(i32) -> i32>(t)(value) }
        }
        #[inline(always)]
        unsafe fn limit(t: usize, value: i32) -> i32 {
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(i32, i32, i32) -> i32>(t)(
                    value, 5, -5,
                )
            }
        }
        #[inline(always)]
        unsafe fn minimum(samples: u32, output: usize) {
            unsafe { __opensensor_rx_dc_minimum(samples, 1, output) }
        }
        #[inline(always)]
        unsafe fn delay(value: u32) {
            unsafe { ets_delay_us(value) }
        }
        #[inline(always)]
        unsafe fn log(kind: u32, a: &[u32]) {
            unsafe {
                match kind {
                    0 => phy_printf(c" (%d,%d) ".as_ptr().cast(), a[0], a[1]),
                    1 => phy_printf(c"%d,%d ".as_ptr().cast(), a[0], a[1]),
                    2 => phy_printf(
                        c"stage %d: CGAIN=%d FGAIN=%d, (%d,%d) %d; ".as_ptr().cast(),
                        a[0],
                        a[1],
                        a[2],
                        a[3],
                        a[4],
                        a[5],
                    ),
                    3 => phy_printf(c"\n".as_ptr().cast()),
                    _ => unreachable!(),
                }
            }
        }
    }
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub unsafe extern "C" fn __opensensor_dc_search_general(
        samples: u32,
        coefficients: usize,
        delay: u32,
        summary: u32,
        detail: u32,
    ) {
        unsafe { general::<Hardware>(samples, coefficients, delay, summary, detail) }
    }
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub unsafe extern "C" fn __opensensor_dc_search_one_step(
        policy: u32,
        mode: u32,
        samples: u32,
        coefficients: usize,
        output: usize,
        status: usize,
    ) {
        unsafe { one_step::<Hardware>(policy, mode, samples, coefficients, output, status) }
    }
}
