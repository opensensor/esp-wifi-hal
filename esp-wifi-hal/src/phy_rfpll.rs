//! RF PLL programming and channel helpers, with chip-specific ABI/state ordering.
//! Calibration callbacks and ROM helpers retain ownership of the RF hardware.

pub(crate) trait Access {
    unsafe fn param() -> usize;
    unsafe fn read(address: usize, width: usize) -> u32;
    unsafe fn write(address: usize, width: usize, value: u32);
    unsafe fn table() -> usize;
    unsafe fn slot(table: usize, offset: usize) -> usize;
    unsafe fn read_call<const N: usize>(target: usize, args: [u32; N]) -> u32;
    unsafe fn write_call<const N: usize>(target: usize, args: [u32; N]);
    unsafe fn external<const N: usize>(kind: u32, args: [u32; N]);
    unsafe fn internal<const N: usize>(kind: u32, args: [u32; N]) -> u32;
    unsafe fn print(kind: u32, args: [u32; 6]);
    unsafe fn scratch<F: FnOnce(usize) -> u32>(kind: u32, f: F) -> u32;
    unsafe fn init_scratch(address: usize, bytes: &[u8]);
}
const S3: bool = cfg!(esp32s3);
const READ: usize = if S3 { 0x188 } else { 0x1ac };
const WRITE: usize = READ + 8;
const MASK_READ: usize = READ + 12;
const MASK_WRITE: usize = READ + 16;
const SPECIAL: usize = if S3 { 0x2a8 } else { 0x325 };
const SAVED: usize = if S3 { 0x2aa } else { 0x326 };
const ENTER: usize = if S3 { 0x160 } else { 0x184 };
const EXIT: usize = ENTER + 4;
#[inline(always)]
fn byte_argument(v: u32) -> u32 {
    if S3 { v as u8 as u32 } else { v }
}
#[inline(always)]
fn short(v: u32) -> u32 {
    v as i16 as i32 as u32
}
#[inline(always)]
unsafe fn target<A: Access>(slot: usize) -> usize {
    unsafe { A::slot(A::table(), slot) }
}
#[inline(always)]
unsafe fn read<A: Access>(offset: usize, width: usize) -> u32 {
    unsafe { A::read(A::param() + offset, width) }
}
#[inline(always)]
unsafe fn write<A: Access>(offset: usize, width: usize, value: u32) {
    unsafe { A::write(A::param() + offset, width, value) }
}
#[inline(always)]
unsafe fn delay<A: Access>(us: u32) {
    unsafe { A::external(0, [us]) }
}
#[inline(always)]
unsafe fn cap_write<A: Access>(value: u32) {
    unsafe {
        if S3 {
            A::write_call(target::<A>(0x20c), [value]);
        } else {
            A::internal(5, [value]);
        }
    }
}
#[inline(always)]
unsafe fn status<A: Access>() -> u32 {
    unsafe { (A::read_call(target::<A>(READ), [98, 1, 12]) >> 2) & 3 }
}
#[inline(always)]
pub(crate) unsafe fn restart<A: Access>() {
    unsafe {
        for (bit, value) in [(6, 1), (5, 0), (5, 1), (6, 0)] {
            A::write_call(target::<A>(MASK_WRITE), [98, 1, 0, bit, bit, value]);
        }
    }
}
#[inline(always)]
pub(crate) unsafe fn sdm<A: Access>(buffer: usize) {
    unsafe {
        A::write_call(target::<A>(WRITE), [99, 1, 0, 7]);
        for i in 0..3 {
            let table = A::table();
            let value = A::read(buffer + i, 1);
            A::write_call(A::slot(table, WRITE), [99, 1, 3 + i as u32, value]);
        }
        A::write_call(target::<A>(WRITE), [99, 1, 0, 23]);
    }
}
#[inline(always)]
pub(crate) unsafe fn wait<A: Access>() {
    unsafe {
        for _ in 0..100 {
            delay::<A>(20);
            if A::read_call(target::<A>(MASK_READ), [98, 1, 7, 1, 1]) != 0 {
                return;
            }
        }
        A::print(0, [0; 6]);
    }
}
#[inline(always)]
pub(crate) unsafe fn frequency<A: Access>(
    frequency: u32,
    selector: u32,
    offset: u32,
    buffer: usize,
) {
    unsafe {
        let selector = selector as u8;
        let clock = match selector {
            1 => 26u32,
            2 => 32,
            3 if !S3 => 48,
            _ => 40,
        };
        let denominator = clock * 3000;
        let offset = if S3 { short(offset) } else { offset };
        let mut numerator = frequency
            .wrapping_mul(1000)
            .wrapping_add(offset)
            .wrapping_mul(4)
            .wrapping_sub(denominator * 32);
        for i in 0..3 {
            let quotient = ((numerator as i32) / (denominator as i32)) as u8;
            A::write(buffer + i, 1, quotient.into());
            numerator = numerator
                .wrapping_sub(u32::from(quotient) * denominator)
                .wrapping_shl(8);
        }
    }
}
#[inline(always)]
pub(crate) unsafe fn correct_offset<A: Access>(value: u32, mode: u32, stored: usize) {
    unsafe {
        let value = if S3 { short(value) } else { value };
        let mode = byte_argument(mode);
        let scaled = if mode == 0 {
            (value.wrapping_mul(9) as i32) >> 2
        } else {
            (value.wrapping_mul(27) as i32) >> 3
        } as i16;
        let old = A::read(stored, 2) as i16;
        if old == scaled {
            return;
        }
        let delta = (i32::from(scaled) - i32::from(old)) as u32;
        for index in 0..85 {
            let v = A::read(0x6000e0c4, 4);
            A::write(0x6000e0c4, 4, (v & 0xffffff00) | (index * 3 + 1));
            let v = A::read(0x6000e0c0, 4);
            A::write(
                0x6000e148,
                4,
                (v & 0xffffff).wrapping_add(delta) | (v & 0xff000000),
            );
            let v = A::read(0x6000e0c4, 4);
            A::write(0x6000e0c4, 4, v | 0x200);
            let v = A::read(0x6000e0c4, 4);
            A::write(0x6000e0c4, 4, v & !0x200);
        }
        A::write(stored, 2, scaled as u16 as u32);
    }
}
#[inline(always)]
pub(crate) unsafe fn write_cap<A: Access>(value: u32) {
    unsafe {
        let value = if S3 { value as u16 as u32 } else { value };
        A::write_call(target::<A>(WRITE), [98, 1, 1, value & 255]);
        A::write_call(target::<A>(MASK_WRITE), [98, 1, 2, 4, 4, value >> 8]);
    }
}
#[inline(always)]
pub(crate) unsafe fn read_cap<A: Access>() -> u32 {
    unsafe {
        let low = A::read_call(target::<A>(READ), [98, 1, 5]);
        let high = A::read_call(target::<A>(MASK_READ), [98, 1, 7, 2, 2]);
        low.wrapping_add(high << 8) as u16 as u32
    }
}
#[inline(always)]
pub(crate) unsafe fn correct_cap<A: Access>(debug: u32, mode: u32) -> u32 {
    unsafe {
        let (debug, mode) = (byte_argument(debug), byte_argument(mode));
        let initial = A::internal(6, []);
        let first = status::<A>();
        let mut step = if first == 2 { -2i32 } else { 2 };
        let mut attempt = 1u32;
        let mut last = 0;
        let mut candidate;
        let mut success = false;
        loop {
            let raw = A::read_call(
                target::<A>(0x28),
                [
                    short(initial.wrapping_add(attempt.wrapping_mul(step as u32))),
                    511,
                    0,
                ],
            );
            candidate = short(raw);
            if read::<A>(SPECIAL, 1) != 0 && mode != 0 {
                candidate = short(initial);
                break;
            }
            cap_write::<A>(raw as u16 as u32);
            delay::<A>(20);
            last = status::<A>();
            if (first == 1 && last == 0) || (first == 0 && last == 2) || (first == 2 && last == 0) {
                step = if first == 1 {
                    2
                } else if first == 0 {
                    -6
                } else {
                    -4
                };
                success = true;
                break;
            }
            if attempt == 10 {
                cap_write::<A>(initial);
                candidate = short(initial);
                break;
            }
            attempt += 1;
        }
        let mut result = 0;
        if read::<A>(SPECIAL, 1) != 0 && mode != 0 {
            let saved = read::<A>(SAVED, 2);
            cap_write::<A>(saved);
        } else if success {
            let raw = A::read_call(
                target::<A>(0x28),
                [short(candidate.wrapping_add(step as u32)), 511, 0],
            );
            candidate = short(raw);
            cap_write::<A>(raw as u16 as u32);
            delay::<A>(20);
            if status::<A>() == 0 {
                result = short(raw.wrapping_sub(initial));
                if result != 0 {
                    A::external(1, [result]);
                }
            }
        }
        if debug != 0 {
            A::print(1, [result, short(initial), candidate, attempt, first, last]);
        }
        result
    }
}
#[inline(always)]
pub(crate) unsafe fn init_cap<A: Access>() -> u32 {
    unsafe {
        let initial = A::internal(6, []);
        A::write_call(target::<A>(MASK_WRITE), [98, 1, 11, 6, 6, 1]);
        let mut count = 0u32;
        let mut sum = 0u16;
        for pass in 0..2 {
            for i in 0..10 {
                let cap = if pass == 0 {
                    initial.wrapping_sub(i)
                } else {
                    initial.wrapping_add(1 + i)
                } as u16;
                cap_write::<A>(cap.into());
                delay::<A>(20);
                if status::<A>() == 0 {
                    sum = sum.wrapping_add(cap);
                    count += 1;
                } else if count != 0 {
                    break;
                }
            }
        }
        let cap = if count == 0 {
            initial
        } else {
            u32::from(sum) / count
        };
        cap_write::<A>(cap);
        delay::<A>(5);
        (initial << 16) | cap
    }
}
#[inline(always)]
pub(crate) unsafe fn set<A: Access>(
    selector: u32,
    frequency: u32,
    offset: u32,
    buffer: usize,
) -> u32 {
    unsafe {
        A::write_call(target::<A>(MASK_WRITE), [98, 1, 11, 6, 6, 0]);
        let (selector, frequency, offset) = if S3 {
            (
                selector as u8 as u32,
                frequency as u16 as u32,
                short(offset),
            )
        } else {
            (selector, frequency, offset)
        };
        A::internal(3, [frequency, selector, offset, buffer as u32]);
        A::internal(1, [buffer as u32]);
        A::internal(0, []);
        A::internal(2, []);
        delay::<A>(5);
        A::internal(8, [])
    }
}
#[inline(always)]
pub(crate) unsafe fn set_offset<A: Access>(selector: u32, frequency: u32, offset: u32) -> u32 {
    unsafe {
        A::scratch(0, |p| {
            A::internal(
                9,
                [
                    byte_argument(selector),
                    if S3 {
                        frequency as u16 as u32
                    } else {
                        frequency
                    },
                    if S3 { short(offset) } else { offset },
                    p as u32,
                ],
            )
        })
    }
}
#[inline(always)]
pub(crate) unsafe fn set_channel<A: Access>(channel: u32, selector: u32, offset: u32) -> u32 {
    unsafe {
        let channel = if S3 {
            channel as i8 as i32 as u32
        } else {
            channel
        };
        let selector = byte_argument(selector);
        let offset = if S3 { short(offset) } else { offset };
        let frequency = A::read_call(target::<A>(if S3 { 0x1d4 } else { 0x1f8 }), [channel]);
        if read::<A>(0x120, 4) & 32 == 0 {
            A::internal(10, [selector, frequency, offset]);
        } else {
            A::external(
                2,
                [frequency.wrapping_sub(2400) as u8 as u32, offset, selector],
            );
        }
        frequency
    }
}
#[inline(always)]
pub(crate) unsafe fn misc<A: Access>(channel: u32) {
    unsafe {
        A::scratch(1, |p| {
            #[cfg(esp32c3)]
            A::init_scratch(p, &[0xa0, 0x84, 0x8e, 0xe8, 0xee, 0xd2, 0xf2, 0xf8, 0xfe]);
            #[cfg(esp32s3)]
            {
                let v = read::<A>(0xf1, 1);
                A::init_scratch(p, &[v as u8]);
            }
            let count = read::<A>(0x1f6, 1).wrapping_add(1) as u8 as u32;
            let base = A::param() as u32;
            A::external(
                3,
                [
                    0,
                    1,
                    p as u32,
                    base + if S3 { 0x26c } else { 0x2e8 },
                    base + if S3 { 0x290 } else { 0x30c },
                    base + if S3 { 0x210 } else { 0x21c },
                    count,
                    0,
                ],
            );
            0
        });
        if S3 {
            A::write_call(target::<A>(0x24c), [1]);
            A::write_call(target::<A>(0x264), [channel as u8 as u32, 0]);
        } else {
            A::external(4, [1]);
            A::external(5, [channel as u8 as u32, 0]);
        }
    }
}
#[inline(always)]
pub(crate) unsafe fn channel<A: Access>(channel: u32, mode: u32) {
    unsafe {
        let (channel, mode) = if S3 {
            (channel as i8 as i32 as u32, mode as i8 as i32 as u32)
        } else {
            (channel, mode)
        };
        let token = A::read_call(target::<A>(ENTER), []);
        let offset;
        #[cfg(esp32s3)]
        {
            let previous = read::<A>(0x1f2, 1) as i8 as i32 as u32;
            offset = short(read::<A>(0xe0, 2));
            if previous != channel {
                let v = A::read(0x6001c130, 4);
                A::write(0x6001c130, 4, v | 0x1000);
            }
            write::<A>(0x1f4, 1, mode as u8 as u32);
            write::<A>(0x1f2, 1, channel as u8 as u32);
            write::<A>(0x1f3, 1, u32::from(mode != 0));
            write::<A>(SPECIAL, 1, 1);
            A::write_call(target::<A>(8), []);
        }
        #[cfg(esp32c3)]
        {
            write::<A>(0x1f3, 1, u32::from(mode != 0));
            write::<A>(SPECIAL, 1, 1);
            let table = A::table();
            write::<A>(0x1f2, 1, channel as u8 as u32);
            write::<A>(0x1f4, 1, mode as u8 as u32);
            offset = short(read::<A>(0xe0, 2));
            A::write_call(A::slot(table, 8), []);
        }
        A::external(6, [1]);
        let selector = read::<A>(0xf3, 1);
        A::internal(11, [channel, selector, offset]);
        A::write_call(target::<A>(if S3 { 0x6c } else { 0x78 }), [mode]);
        #[cfg(esp32c3)]
        {
            let table = A::table();
            let a = read::<A>(0x11a, 1);
            let b = read::<A>(0x11c, 2);
            let target = A::slot(table, 0x60);
            let c = read::<A>(0xf3, 1);
            let d = read::<A>(0x118, 2);
            A::write_call(target, [channel, mode, 0, c, b, d, a]);
        }
        A::internal(12, [channel]);
        #[cfg(esp32c3)]
        A::external(7, []);
        if read::<A>(0xe6, 1) != 0 {
            A::external(8, [u32::from(channel == 14)]);
        }
        let enabled = read::<A>(0xef, 1);
        if enabled != 0 {
            let value = read::<A>(0xf0, 1);
            A::external(9, [enabled, value]);
        }
        A::external(6, [0]);
        A::write_call(target::<A>(12), []);
        A::write_call(target::<A>(EXIT), [token]);
    }
}
#[inline(always)]
pub(crate) unsafe fn channel_offset<A: Access>(offset: u32) {
    unsafe {
        let offset = if S3 { short(offset) } else { offset };
        let token = A::read_call(target::<A>(ENTER), []);
        let rounded = short(offset.wrapping_add(2) & !3);
        #[cfg(esp32s3)]
        let adjust = read::<A>(0x11e, 1);
        write::<A>(0xe0, 2, rounded as u16 as u32);
        #[cfg(esp32c3)]
        let adjust = read::<A>(0x11e, 1);
        if adjust != 0 {
            let v = read::<A>(0x11f, 1) as i8 as i32;
            write::<A>(0xe0, 2, rounded.wrapping_add((v * 8) as u32) as u16 as u32);
        }
        let offset = short(read::<A>(0xe0, 2));
        A::external(10, [1, offset]);
        A::write_call(target::<A>(8), []);
        #[cfg(esp32s3)]
        let channel = read::<A>(0x1f2, 1) as i8 as i32 as u32;
        let offset = short(read::<A>(0xe0, 2));
        let selector = read::<A>(0xf3, 1);
        #[cfg(esp32c3)]
        let channel = read::<A>(0x1f2, 1) as i8 as i32 as u32;
        A::internal(11, [channel, selector, offset]);
        A::write_call(target::<A>(12), []);
        A::write_call(target::<A>(EXIT), [token]);
    }
}
#[inline(always)]
pub(crate) unsafe fn channel_analog<A: Access>(channel: u32) {
    unsafe {
        let channel = if S3 {
            channel as i8 as i32 as u32
        } else {
            channel
        };
        let selector = read::<A>(0xf3, 1);
        A::internal(11, [channel, selector, 0]);
        write::<A>(0x1f2, 1, channel as u8 as u32);
    }
}
#[cfg(esp32s3)]
#[inline(always)]
pub(crate) unsafe fn phy_frequency<A: Access>(frequency: u32, offset: u32) -> u32 {
    unsafe {
        A::scratch(0, |p| {
            let selector = read::<A>(0xf3, 1);
            A::internal(
                9,
                [selector, frequency as u16 as u32, short(offset), p as u32],
            )
        })
    }
}

#[cfg(not(test))]
mod native {
    use super::Access;
    unsafe extern "C" {
        static mut phy_param: u8;
        static mut g_phyFuns: *const u8;
        fn ets_delay_us(us: u32);
        #[cfg_attr(esp32c3, link_name = "rom2_pll_cap_mem_update")]
        #[cfg_attr(esp32s3, link_name = "pll_cap_mem_update")]
        fn cap_mem_update(delta: u32);
        fn set_chan_freq_sw_start(frequency: u32, offset: u32, selector: u32);
        fn wr_rx_gain_mem(
            a: u32,
            b: u32,
            c: *const u8,
            d: *mut u8,
            e: *mut u8,
            f: *mut u8,
            g: u32,
            h: u32,
        );
        #[cfg(esp32c3)]
        fn rom_set_chan_reg(mode: u32);
        #[cfg(esp32c3)]
        fn ram1_wifi_set_tx_gain(channel: u32, mode: u32);
        fn force_txrx_off(enabled: u32);
        #[cfg(esp32c3)]
        fn get_txcap_data();
        fn chan14_mic_cfg(enabled: u32);
        fn phy_11p_set(enabled: u32, value: u32);
        fn phy_freq_correct(mode: u32, offset: u32);
        fn phy_printf(format: *const core::ffi::c_char, ...);
    }
    pub(super) struct Native;
    impl Access for Native {
        #[inline(always)]
        unsafe fn param() -> usize {
            (&raw const phy_param) as usize
        }
        #[inline(always)]
        unsafe fn read(address: usize, width: usize) -> u32 {
            unsafe {
                match width {
                    1 => (address as *const u8).read_volatile().into(),
                    2 => (address as *const u16).read_volatile().into(),
                    4 => (address as *const u32).read_volatile(),
                    _ => unreachable!(),
                }
            }
        }
        #[inline(always)]
        unsafe fn write(address: usize, width: usize, value: u32) {
            unsafe {
                match width {
                    1 => (address as *mut u8).write_volatile(value as u8),
                    2 => (address as *mut u16).write_volatile(value as u16),
                    4 => (address as *mut u32).write_volatile(value),
                    _ => unreachable!(),
                }
            }
        }
        #[inline(always)]
        unsafe fn table() -> usize {
            unsafe { (&raw const g_phyFuns).read_volatile() as usize }
        }
        #[inline(always)]
        unsafe fn slot(table: usize, offset: usize) -> usize {
            unsafe { ((table + offset) as *const usize).read_volatile() }
        }
        #[inline(always)]
        unsafe fn read_call<const N: usize>(target: usize, a: [u32; N]) -> u32 {
            unsafe {
                match N {
                    0 => core::mem::transmute::<usize, unsafe extern "C" fn() -> u32>(target)(),
                    1 => core::mem::transmute::<usize, unsafe extern "C" fn(u32) -> u32>(target)(
                        a[0],
                    ),
                    3 => core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32, u32) -> u32>(
                        target,
                    )(a[0], a[1], a[2]),
                    5 => core::mem::transmute::<
                        usize,
                        unsafe extern "C" fn(u32, u32, u32, u32, u32) -> u32,
                    >(target)(a[0], a[1], a[2], a[3], a[4]),
                    _ => unreachable!(),
                }
            }
        }
        #[inline(always)]
        unsafe fn write_call<const N: usize>(target: usize, a: [u32; N]) {
            unsafe {
                match N {
                    0 => core::mem::transmute::<usize, unsafe extern "C" fn()>(target)(),
                    1 => core::mem::transmute::<usize, unsafe extern "C" fn(u32)>(target)(a[0]),
                    2 => core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32)>(target)(
                        a[0], a[1],
                    ),
                    4 => core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32, u32, u32)>(
                        target,
                    )(a[0], a[1], a[2], a[3]),
                    6 => core::mem::transmute::<
                        usize,
                        unsafe extern "C" fn(u32, u32, u32, u32, u32, u32),
                    >(target)(a[0], a[1], a[2], a[3], a[4], a[5]),
                    7 => core::mem::transmute::<
                        usize,
                        unsafe extern "C" fn(u32, u32, u32, u32, u32, u32, u32),
                    >(target)(a[0], a[1], a[2], a[3], a[4], a[5], a[6]),
                    _ => unreachable!(),
                }
            }
        }
        #[inline(always)]
        unsafe fn external<const N: usize>(kind: u32, a: [u32; N]) {
            unsafe {
                match kind {
                    0 => ets_delay_us(a[0]),
                    1 => cap_mem_update(a[0]),
                    2 => set_chan_freq_sw_start(a[0], a[1], a[2]),
                    3 => wr_rx_gain_mem(
                        a[0],
                        a[1],
                        a[2] as *const u8,
                        a[3] as *mut u8,
                        a[4] as *mut u8,
                        a[5] as *mut u8,
                        a[6],
                        a[7],
                    ),
                    #[cfg(esp32c3)]
                    4 => rom_set_chan_reg(a[0]),
                    #[cfg(esp32c3)]
                    5 => ram1_wifi_set_tx_gain(a[0], a[1]),
                    6 => force_txrx_off(a[0]),
                    #[cfg(esp32c3)]
                    7 => get_txcap_data(),
                    8 => chan14_mic_cfg(a[0]),
                    9 => phy_11p_set(a[0], a[1]),
                    10 => phy_freq_correct(a[0], a[1]),
                    _ => unreachable!(),
                }
            }
        }
        #[inline(always)]
        unsafe fn print(kind: u32, a: [u32; 6]) {
            unsafe {
                match kind {
                    0 => {
                        phy_printf(c"error: pll_cal exceeds 2ms!!!\n".as_ptr());
                    }
                    1 => {
                        phy_printf(
                            c"%d,%d,%d,%d,%d,%d\n".as_ptr(),
                            a[0],
                            a[1],
                            a[2],
                            a[3],
                            a[4],
                            a[5],
                        );
                    }
                    _ => unreachable!(),
                }
            }
        }
        #[inline(always)]
        unsafe fn scratch<F: FnOnce(usize) -> u32>(_kind: u32, f: F) -> u32 {
            let mut buffer = core::mem::MaybeUninit::<[u32; 4]>::uninit();
            f(buffer.as_mut_ptr() as usize)
        }
        #[inline(always)]
        unsafe fn init_scratch(address: usize, bytes: &[u8]) {
            unsafe {
                core::ptr::copy_nonoverlapping(bytes.as_ptr(), address as *mut u8, bytes.len());
            }
        }
        #[inline(always)]
        unsafe fn internal<const N: usize>(kind: u32, a: [u32; N]) -> u32 {
            unsafe {
                match kind {
                    0 => {
                        super::__opensensor_rfpll_restart();
                        0
                    }
                    1 => {
                        super::__opensensor_rfpll_sdm(a[0]);
                        0
                    }
                    2 => {
                        super::__opensensor_rfpll_wait();
                        0
                    }
                    3 => {
                        super::__opensensor_rfpll_frequency(a[0], a[1], a[2], a[3]);
                        0
                    }
                    4 => {
                        super::__opensensor_rfpll_correct_offset(a[0], a[1], a[2]);
                        0
                    }
                    5 => {
                        super::__opensensor_rfpll_write_cap(a[0]);
                        0
                    }
                    6 => super::__opensensor_rfpll_read_cap(),
                    7 => super::__opensensor_rfpll_correct_cap(a[0], a[1]),
                    8 => super::__opensensor_rfpll_init_cap(),
                    9 => {
                        super::__opensensor_rfpll_set(a[0], a[1], a[2], a[3]);
                        0
                    }
                    10 => {
                        super::__opensensor_rfpll_set_offset(a[0], a[1], a[2]);
                        0
                    }
                    11 => super::__opensensor_rfpll_set_channel(a[0], a[1], a[2]),
                    12 => {
                        super::__opensensor_rfpll_misc(a[0]);
                        0
                    }
                    13 => {
                        super::__opensensor_rfpll_channel(a[0], a[1]);
                        0
                    }
                    14 => {
                        super::__opensensor_rfpll_channel_offset(a[0]);
                        0
                    }
                    15 => {
                        super::__opensensor_rfpll_channel_analog(a[0]);
                        0
                    }
                    #[cfg(esp32s3)]
                    16 => {
                        super::__opensensor_rfpll_phy_frequency(a[0], a[1]);
                        0
                    }
                    #[cfg(esp32s3)]
                    17 => super::__opensensor_rfpll_voltage(),
                    _ => unreachable!(),
                }
            }
        }
    }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_rfpll_restart() {
    unsafe {
        restart::<native::Native>();
    }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_rfpll_sdm(a0: u32) {
    unsafe {
        sdm::<native::Native>(a0 as usize);
    }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_rfpll_wait() {
    unsafe {
        wait::<native::Native>();
    }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_rfpll_frequency(a0: u32, a1: u32, a2: u32, a3: u32) {
    unsafe {
        frequency::<native::Native>(a0, a1, a2, a3 as usize);
    }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_rfpll_correct_offset(a0: u32, a1: u32, a2: u32) {
    unsafe {
        correct_offset::<native::Native>(a0, a1, a2 as usize);
    }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_rfpll_write_cap(a0: u32) {
    unsafe {
        write_cap::<native::Native>(a0);
    }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_rfpll_read_cap() -> u32 {
    unsafe { read_cap::<native::Native>() }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_rfpll_correct_cap(a0: u32, a1: u32) -> u32 {
    unsafe { correct_cap::<native::Native>(a0, a1) }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_rfpll_init_cap() -> u32 {
    unsafe { init_cap::<native::Native>() }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_rfpll_set(a0: u32, a1: u32, a2: u32, a3: u32) {
    unsafe {
        set::<native::Native>(a0, a1, a2, a3 as usize);
    }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_rfpll_set_offset(a0: u32, a1: u32, a2: u32) {
    unsafe {
        set_offset::<native::Native>(a0, a1, a2);
    }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_rfpll_set_channel(a0: u32, a1: u32, a2: u32) -> u32 {
    unsafe { set_channel::<native::Native>(a0, a1, a2) }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_rfpll_misc(a0: u32) {
    unsafe {
        misc::<native::Native>(a0);
    }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_rfpll_channel(a0: u32, a1: u32) {
    unsafe {
        channel::<native::Native>(a0, a1);
    }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_rfpll_channel_offset(a0: u32) {
    unsafe {
        channel_offset::<native::Native>(a0);
    }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_rfpll_channel_analog(a0: u32) {
    unsafe {
        channel_analog::<native::Native>(a0);
    }
}
#[cfg(esp32s3)]
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_rfpll_phy_frequency(a0: u32, a1: u32) {
    unsafe {
        phy_frequency::<native::Native>(a0, a1);
    }
}
#[cfg(esp32s3)]
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_rfpll_voltage() -> u32 {
    0
}
