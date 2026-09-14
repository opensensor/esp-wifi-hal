unsafe extern "C" {
    static mut phy_param: u8;
    static mut g_phyFuns: usize;
    fn chip_v7_set_chan(channel: u32, mode: u32);
    fn phy_set_freq(frequency: u32, mode: u32);
    fn start_tx_tone_step(enable: u32, frequency: u32, gain: u32, a: u32, b: u32, c: u32);
    fn phy_printf(format: *const u8, ...);
}

struct Hardware;
impl Access for Hardware {
    #[inline(always)]
    unsafe fn read(address: usize, width: usize) -> u32 {
        unsafe {
            match width {
                1 => core::ptr::read_volatile(address as *const u8) as u32,
                4 => core::ptr::read_volatile(address as *const u32),
                _ => unreachable!(),
            }
        }
    }
    #[inline(always)]
    unsafe fn write(address: usize, width: usize, value: u32) {
        unsafe {
            match width {
                1 => core::ptr::write_volatile(address as *mut u8, value as u8),
                4 => core::ptr::write_volatile(address as *mut u32, value),
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
    unsafe fn quotient(numerator: i32, denominator: i32) -> i32 {
        let result;
        unsafe {
            // The memory clobber preserves observed effects before a zero fault.
            core::arch::asm!("quos {result}, {numerator}, {denominator}",
                            result = out(reg) result, numerator = in(reg) numerator,
                            denominator = in(reg) denominator, options(nostack));
        }
        result
    }
    #[inline(always)]
    unsafe fn call(target: usize, kind: u32, args: &[u32]) -> u32 {
        unsafe {
            match kind {
                0 => {
                    return core::mem::transmute::<usize, unsafe extern "C" fn(u32) -> u32>(target)(
                        args[0],
                    );
                }
                1 => {
                    return core::mem::transmute::<
                        usize,
                        unsafe extern "C" fn(u32, u32, u32, u32) -> u32,
                    >(target)(args[0], args[1], args[2], args[3]);
                }
                2 | 3 | 4 => core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32)>(target)(
                    args[0], args[1],
                ),
                5 => core::mem::transmute::<usize, unsafe extern "C" fn()>(target)(),
                6 => {
                    return core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32) -> u32>(
                        target,
                    )(args[0], args[1]);
                }
                7 => chip_v7_set_chan(args[0], args[1]),
                8 => phy_set_freq(args[0], args[1]),
                9 => start_tx_tone_step(args[0], args[1], args[2], args[3], args[4], args[5]),
                10 => phy_printf(
                    c"i=%d,%d,%d,%d\n".as_ptr().cast(),
                    args[1],
                    args[2],
                    args[3],
                    args[4],
                ),
                _ => unreachable!(),
            }
        }
        0
    }
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn __opensensor_spur_config(
    a: u32,
    b: u32,
    c: u32,
    d: u32,
    e: u32,
    f: u32,
    g: u32,
) {
    unsafe {
        phy_spur::configure::<Hardware>([a, b, c, d, e, f, g]);
    }
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn __opensensor_spur_power(logging: u32) {
    unsafe {
        phy_spur::power::<Hardware>(logging);
    }
}
