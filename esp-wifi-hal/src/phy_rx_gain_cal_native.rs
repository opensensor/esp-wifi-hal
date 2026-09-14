#[cfg(all(not(test), any(target_arch = "riscv32", target_arch = "xtensa")))]
mod native {
    use super::*;
    use core::ptr::{read_volatile, write_volatile};
    unsafe extern "C" {
        static mut g_phyFuns: usize;
        static mut phy_param: u8;
        fn pbus_rx_dco_cal(
            samples: u32,
            coefficients: usize,
            delay: u32,
            summary: u32,
            detail: u32,
        );
        #[cfg(esp32c3)]
        fn pbus_rx_dco_cal_1step_new(
            policy: u32,
            mode: u32,
            samples: u32,
            coefficients: usize,
            output: usize,
            status: usize,
        );
        #[cfg(esp32s3)]
        fn pbus_rx_dco_cal_1step(
            policy: u32,
            mode: u32,
            samples: u32,
            coefficients: usize,
            output: usize,
            status: usize,
        );
        fn txiq_set_reg(value: u32, mode: u32);
        fn start_tx_tone_step(enable: u32, frequency: u32, gain: u32, a: u32, b: u32, c: u32);
        fn stop_tx_tone(enable: u32);
        fn get_rfcal_rxiq_data(frequency: u32, gain: u32, logging: u32) -> u32;
        fn chip_v7_set_chan_ana(channel: u32);
        fn rx_chan_dc_sort(data: usize, status: usize);
        fn phy_printf(format: *const u8, ...);
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
        unsafe fn parameter() -> usize {
            (&raw const phy_param) as usize
        }
        #[inline(always)]
        unsafe fn table_global() -> usize {
            (&raw const g_phyFuns) as usize
        }
        #[inline(always)]
        unsafe fn local(p: *mut u8, _: u32, _: usize) -> usize {
            p as usize
        }
        #[inline(always)]
        unsafe fn call(t: usize, k: u32, a: &[usize]) -> u32 {
            unsafe {
                match k {
                    0 => {
                        return core::mem::transmute::<
                            usize,
                            unsafe extern "C" fn(u32, u32, u32, u32, u32) -> u32,
                        >(t)(
                            a[0] as u32,
                            a[1] as u32,
                            a[2] as u32,
                            a[3] as u32,
                            a[4] as u32,
                        );
                    }
                    1 => core::mem::transmute::<
                        usize,
                        unsafe extern "C" fn(u32, u32, u32, u32, u32, u32),
                    >(t)(
                        a[0] as u32,
                        a[1] as u32,
                        a[2] as u32,
                        a[3] as u32,
                        a[4] as u32,
                        a[5] as u32,
                    ),
                    2 | 3 | 4 | 10 => {
                        core::mem::transmute::<usize, unsafe extern "C" fn(u32)>(t)(a[0] as u32)
                    }
                    5 | 6 => core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32, u32)>(t)(
                        a[0] as u32,
                        a[1] as u32,
                        a[2] as u32,
                    ),
                    7 => {
                        return core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32) -> u32>(
                            t,
                        )(a[0] as u32, a[1] as u32);
                    }
                    8 => core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32)>(t)(
                        a[0] as u32,
                        a[1] as u32,
                    ),
                    9 => core::mem::transmute::<usize, unsafe extern "C" fn()>(t)(),
                    20 => pbus_rx_dco_cal(a[0] as u32, a[1], a[2] as u32, a[3] as u32, a[4] as u32),
                    21 => {
                        #[cfg(esp32c3)]
                        pbus_rx_dco_cal_1step_new(
                            a[0] as u32,
                            a[1] as u32,
                            a[2] as u32,
                            a[3],
                            a[4],
                            a[5],
                        );
                        #[cfg(esp32s3)]
                        pbus_rx_dco_cal_1step(
                            a[0] as u32,
                            a[1] as u32,
                            a[2] as u32,
                            a[3],
                            a[4],
                            a[5],
                        );
                    }
                    22 => txiq_set_reg(a[0] as u32, a[1] as u32),
                    23 => start_tx_tone_step(
                        a[0] as u32,
                        a[1] as u32,
                        a[2] as u32,
                        a[3] as u32,
                        a[4] as u32,
                        a[5] as u32,
                    ),
                    24 => stop_tx_tone(a[0] as u32),
                    25 => return get_rfcal_rxiq_data(a[0] as u32, a[1] as u32, a[2] as u32),
                    26 => chip_v7_set_chan_ana(a[0] as u32),
                    27 => rx_chan_dc_sort(a[0], a[1]),
                    29 => {
                        if a[0] == 0 {
                            phy_printf(c"total_pwr=%ld, min=%ld, max=%ld, rftx=0x%x, bb=0x%x, att=%d, dc_i=%d, dc_q=%d\n".as_ptr().cast(),a[1] as u32,a[2] as u32,a[3] as u32,a[4] as u32,a[5] as u32,a[6] as u32,a[7] as u32,a[8] as u32);
                        } else {
                            phy_printf(
                                c"rxiq: rftx=0x%x, rfrx=x%x, att=%d, bb=0x%x, %d, %d\n"
                                    .as_ptr()
                                    .cast(),
                                a[1] as u32,
                                a[2] as u32,
                                a[3] as u32,
                                a[4] as u32,
                                a[5] as u32,
                                a[6] as u32,
                            );
                        }
                    }
                    _ => unreachable!(),
                }
                0
            }
        }
    }
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub unsafe extern "C" fn __opensensor_rx_gain_cal_iq(
        policy: u32,
        frequency: u32,
        output: usize,
        logging: u32,
    ) {
        unsafe { iq::<Hardware>(policy, frequency, output, logging) }
    }
    #[cfg(esp32c3)]
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub unsafe extern "C" fn __opensensor_rx_gain_cal_dc(
        a: usize,
        b: usize,
        c: usize,
        d: usize,
        e: usize,
        f: usize,
        g: usize,
        h: usize,
    ) {
        unsafe { dc::<Hardware>(&[a, b, c, d, e, f, g, h, 0, 0]) }
    }
    #[cfg(esp32s3)]
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub unsafe extern "C" fn __opensensor_rx_gain_cal_dc(
        a: usize,
        b: usize,
        c: usize,
        d: usize,
        e: usize,
        f: usize,
        g: usize,
        h: usize,
        i: usize,
        _unused: usize,
    ) {
        unsafe { dc::<Hardware>(&[a, b, c, d, e, f, g, h, i, 0]) }
    }
}
