#[cfg(all(not(test), any(target_arch = "riscv32", target_arch = "xtensa")))]
mod native {
    use super::*;
    use core::ptr::{read_volatile, write_volatile};
    unsafe extern "C" {
        static mut g_phyFuns: usize;
        static mut phy_param: u8;
    }
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
        unsafe fn parameter_address() -> usize {
            (&raw const phy_param) as usize
        }
        #[inline(always)]
        unsafe fn local(p: *mut u32) -> usize {
            p as usize
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
        unsafe fn difference(t: usize, v: i32) -> i32 {
            unsafe { core::mem::transmute::<usize, unsafe extern "C" fn(i32) -> i32>(t)(v) }
        }
    }
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub unsafe extern "C" fn __opensensor_rx_dc_minimum(samples: u32, unused: u32, output: usize) {
        unsafe { minimum::<Hardware>(samples, unused, output) }
    }
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub unsafe extern "C" fn __opensensor_rx_dc_sort(data: usize, status: usize) {
        unsafe { sort::<Hardware>(data, status) }
    }
}
