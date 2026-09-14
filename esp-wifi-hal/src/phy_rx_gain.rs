//! Receive-gain table construction and calibration sequencing.
//!
//! Pointer extents and gain ranges follow the PHY caller contract. In particular,
//! coefficient indices must stay within the five-entry gain encoding table.

pub(crate) trait Access {
    unsafe fn param() -> usize;
    unsafe fn read(address: usize, width: usize) -> u32;
    unsafe fn write(address: usize, width: usize, value: u32);
    unsafe fn table() -> usize;
    unsafe fn slot(table: usize, offset: usize) -> usize;
    unsafe fn call(target: usize, args: &[u32]) -> u32;
    unsafe fn external(kind: u32, args: &[usize]);
    unsafe fn log(kind: u32, args: &[u32]);
    unsafe fn local(pointer: *mut u32, tag: usize, size: usize) -> usize;
    unsafe fn copy(destination: usize, offset: usize, size: usize);
    unsafe fn child(kind: u32, args: &[usize]) -> u32;
}
const S3: bool = cfg!(esp32s3);
const COEFFICIENTS: [u16; 5] = [0, 1, 5, 13, 29];
#[inline(always)]
fn byte(v: u32) -> u32 {
    if S3 { v as u8 as u32 } else { v }
}
#[inline(always)]
unsafe fn update<A: Access>(address: usize, mask: u32, value: u32) {
    unsafe {
        let old = A::read(address, 4);
        A::write(address, 4, (old & mask) | value);
    }
}
#[inline(always)]
unsafe fn target<A: Access>(offset: usize) -> usize {
    unsafe { A::slot(A::table(), offset) }
}

/// Seven machine arguments: output, maximum gain, codes, steps, starts, count, log.
#[inline(always)]
pub(crate) unsafe fn generate<A: Access>(a: &[usize]) -> u32 {
    unsafe {
        let (out, codes, steps, starts) = (a[0], a[2], a[3], a[4]);
        let max = byte(a[1] as u32);
        let count = byte(a[5] as u32);
        let logging = byte(a[6] as u32) != 0;
        let mut gain = A::read(starts, 1);
        let mut input = 0u32;
        let mut index = 0u32;
        loop {
            let step = A::read(steps + input as usize, 1) as i8 as i32;
            let start = A::read(starts + input as usize, 1) as i8 as i32;
            if gain as i32 == step + start && (input as i32) < count.wrapping_sub(1) as i32 {
                loop {
                    input = input.wrapping_add(1) & 255;
                    if A::read(steps + input as usize, 1) != 0
                        || (input as i32) >= count.wrapping_sub(1) as i32
                    {
                        break;
                    }
                }
                gain = A::read(starts + input as usize, 1);
            }
            let shifted = (COEFFICIENTS[(gain / 6) as usize] as u32 * 8) & 65535;
            let remainder = gain % 6;
            let code = A::read(codes + input as usize, 1);
            let packed = ((code << 8) + shifted + remainder) & 65535;
            let address = out + ((index as i8 as i32 >> 1) * 4) as usize;
            if index & 1 != 0 {
                let old = A::read(address, 4);
                A::write(address, 4, old.wrapping_add(packed << 16));
            } else {
                A::write(address, 4, packed);
            }
            if logging {
                let step = A::read(steps + input as usize, 1) as i8 as i32 as u32;
                let code = A::read(codes + input as usize, 1);
                A::log(
                    0,
                    &[index, packed, code, shifted, remainder, count, input, step],
                );
            }
            if max < gain {
                if logging {
                    A::log(1, &[index]);
                }
                return index & 255;
            }
            gain = (gain + 1) & 255;
            index += 1;
            if index == 127 {
                return 85;
            }
        }
    }
}
#[inline(always)]
pub(crate) unsafe fn write_memory<A: Access>(a: &[usize]) {
    unsafe {
        let mode = byte(a[0] as u32);
        let alternate = byte(a[1] as u32) != 0;
        let (codes, iq, dc, extra, packed) = (a[2], a[3], a[4], a[5], a[7]);
        let count = byte(a[6] as u32);
        let starts: [u8; 15] = if S3 {
            [0, 0, 0, 0, 0, 4, 4, 8, 0, 0, 0, 0, 0, 0, 0]
        } else {
            [0, 2, 1, 3, 6, 3, 12, 11, 10, 0, 0, 0, 0, 0, 0]
        };
        let steps: [u8; 15] = if S3 {
            [7, 13, 10, 5, 12, 8, 5, 9, 0, 0, 0, 0, 0, 0, 0]
        } else {
            [9, 12, 11, 8, 9, 12, 4, 4, 0, 0, 0, 0, 0, 0, 0]
        };
        let total = steps[..if S3 { 8 } else { 6 }]
            .iter()
            .fold(0u8, |sum, v| sum.wrapping_add(*v)) as u32;
        let mut index = if alternate { total } else { 0 };
        let mut input = if !S3 && alternate { 6u32 } else { 0 };
        let mut gain = if S3 { 8 } else { starts[input as usize] as u32 };
        while index < count {
            let word;
            if alternate {
                if !S3
                    && (gain as i32)
                        >= steps[input as usize] as i32 + starts[input as usize] as i8 as i32
                    && input <= 7
                {
                    input = (input + 1) & 255;
                    gain = starts[input as usize] as u32;
                }
                let encoded = ((COEFFICIENTS[(gain / 6) as usize] as u32 * 8) + (gain % 6)) & 255;
                let code = A::read(codes + if S3 { 0 } else { input as usize }, 1);
                word = (code << 8) | encoded;
            } else if S3 {
                word = A::read(
                    packed + (index as usize / 2) * 4 + (index as usize & 1) * 2,
                    2,
                );
                gain = (((word >> 3) & 63).count_ones() * 6 + (word & 7)) & 255;
            } else {
                let value = A::read(packed + ((index << 1) & 1020) as usize, 4);
                word = if index & 1 != 0 {
                    value >> 16
                } else {
                    value & 65535
                };
                let code = A::read(codes + input as usize, 1);
                if word & 0xffffff00 != code << 8 {
                    input = (input + 1) & 255;
                }
            }
            let iq_value;
            if mode == 0 && index >= total {
                let p = A::param();
                let value = A::read(p + 0x1f2, 1) as i8 as i32;
                let offset = if S3 {
                    value.wrapping_sub(1)
                } else {
                    value
                        .wrapping_sub(1)
                        .wrapping_mul(3)
                        .wrapping_sub(6)
                        .wrapping_add(input as i32)
                } as u16 as usize;
                iq_value = A::read(extra + offset * 4, 4);
            } else {
                if S3 {
                    let code = A::read(codes + input as usize, 1);
                    if word & 0xffffff00 != code << 8 {
                        input = (input + 1) & 255;
                    }
                }
                iq_value = A::read(iq + input as usize * 4, 4);
            }
            let (dc_value, correction) = if mode != 0 {
                (0x01000100, 0)
            } else {
                let bits = ((word >> 3) & 63).count_ones();
                let dc_value = A::read(dc + bits.min(3) as usize * 4, 4);
                let p = A::param();
                let v = A::read(p + 0x150 + if word & 0xf8 != 0 { 2 } else { 0 }, 2);
                (dc_value, ((v >> 7) << 6) | (v & 63))
            };
            let hi = dc_value >> 16;
            let table = A::table();
            let callback = A::slot(table, 0x2c);
            let first = (word << 17)
                .wrapping_add((iq_value >> 16) << 8)
                .wrapping_add((hi as i32 >> 1) as u32);
            let second = (hi << 31)
                .wrapping_add((iq_value & 65535) << 22)
                .wrapping_add((dc_value & 65535) << 13)
                .wrapping_add((correction << 2) & 0x1ffc)
                .wrapping_add(if !S3 && mode != 0 { 3 } else { 0 });
            A::call(
                callback,
                &[
                    first,
                    second,
                    (index
                        + if mode != 0 {
                            if S3 { 83 } else { 80 }
                        } else {
                            0
                        })
                        & 255,
                ],
            );
            if alternate {
                gain = (gain + 1) & 255;
            }
            index = (index + 1) & 255;
        }
    }
}

#[inline(always)]
pub(crate) unsafe fn set_param<A: Access>(a: &[usize]) {
    unsafe {
        let mode = byte(a[0] as u32);
        let codes = a[2];
        let count = byte(a[5] as u32);
        let p = A::param();
        let (enter, exit, read, write, select) = if S3 {
            (0x1b0, 0x1b4, 0x1ac, 0x1a8, 0x1c0)
        } else {
            (0x1d4, 0x1d8, 0x1d0, 0x1cc, 0x1e4)
        };
        update::<A>(0x60006110, u32::MAX, 0x4000);
        update::<A>(0x60006110, u32::MAX, 0x8000);
        A::call(target::<A>(enter), &[]);
        A::call(target::<A>(select), &[0]);
        if mode != 0 {
            let t = A::table();
            let w = A::slot(t, write);
            let r = A::slot(t, read);
            let value = A::call(r, &[1, 1]);
            A::call(w, &[1, 1, (value | 2) & 65535]);
        } else if A::read(p + 0x120, 4) & 1024 == 0 {
            A::external(0, &[0, 128, p + 0x150, 0]);
            let v = A::read(p + 0x120, 4);
            A::write(p + 0x120, 4, v | 1024);
        }
        update::<A>(0x6000607c, 0xf7ffffff, 0);
        A::call(target::<A>(select), &[0]);
        if mode != 0 {
            let t = A::table();
            let w = A::slot(t, write);
            let r = A::slot(t, read);
            let value = A::call(r, &[1, 1]);
            A::call(w, &[1, 1, (value | 2) & 65535]);
            A::call(target::<A>(write), &[4, 2, if S3 { 0 } else { 24 }]);
        }
        let mut args = [
            if mode != 0 { 1 } else { 0 },
            0,
            if mode != 0 { 1 } else { 3 },
            codes,
            p + if S3 { 0x248 } else { 0x2c4 },
            p + if S3 { 0x290 } else { 0x30c },
            p + if S3 { 0x210 } else { 0x21c },
            count as usize,
            if mode == 0 { 4 } else { 0 },
            if mode == 0 { 14 } else { 0 },
        ];
        A::external(1, &mut args[..if S3 { 10 } else { 8 }]);
        update::<A>(0x60006110, 0xffff7fff, 0);
        if mode != 0 {
            A::call(target::<A>(write), &[4, 2, 0]);
        }
        A::call(target::<A>(select), &[0]);
        A::call(target::<A>(exit), &[]);
    }
}

#[inline(always)]
pub(crate) unsafe fn initialize<A: Access>() {
    unsafe {
        let p = A::param();
        A::write(p + 0x1f6, 1, if S3 { 82 } else { 79 });
        A::write(p + 0x1f5, 1, if S3 { 76 } else { 79 });
        for index in 0..if S3 { 82 } else { 79 } {
            A::call(target::<A>(0x2c), &[0x10080, 0x40200000, index]);
        }
        if S3 {
            A::call(target::<A>(0x248), &[]);
        } else {
            A::external(3, &[]);
        }
        A::call(target::<A>(4), &[]);
    }
}

#[inline(always)]
pub(crate) unsafe fn set_table<A: Access>(frequency: u32, requested: u32) {
    unsafe {
        // Separate buffers retain the original copy order and child-call boundaries.
        let mut storage = core::mem::MaybeUninit::<[u32; 128]>::uninit();
        let b = A::local(storage.as_mut_ptr().cast(), 0, 512);
        let (code0, code1, step0, step1, start0, start1, out1, out0) =
            (b, b + 12, b + 24, b + 40, b + 56, b + 72, b + 88, b + 288);
        for (destination, offset, size) in [
            (code0, if S3 { 25 } else { 32 }, 9),
            (code1, if S3 { 34 } else { 32 }, 9),
            (step0, if S3 { 10 } else { 0 }, 15),
            (step1, if S3 { 43 } else { 44 }, 15),
            (start0, if S3 { 58 } else { 16 }, 15),
            (start1, if S3 { 73 } else { 60 }, 15),
        ] {
            A::copy(destination, offset, size);
        }
        let count = (9u32.wrapping_sub(byte(requested))) & 255;
        let value = A::read(code0.wrapping_add(count as usize).wrapping_sub(1), 1);
        let p = A::param();
        A::write(p + 0xf1, 1, value);
        let mut input1 = 9;
        let mut input0 = 9;
        if !S3 {
            if A::read(p + 0x218, 1) & 2 != 0 {
                A::write(code1 + 8, 1, 0);
                A::write(code1 + 7, 1, 0);
                A::write(step1 + 6, 2, 0);
                input1 = 7;
            }
            if (A::read(p + 0x348, 1) as i8) < -6 {
                input0 = 5;
            }
        }
        if A::read(p + 0x120, 4) & 512 == 0 {
            let maximum1 = if S3 { 76 } else { 79 };
            let maximum0 = if S3 { 82 } else { 79 };
            let result = A::child(0, &[out1, 22, code1, step1, start1, input1, 0]);
            A::write(p + 0x1f5, 1, result.min(maximum1));
            let result = A::child(
                0,
                &[
                    out0,
                    if S3 { 25 } else { 22 },
                    code0,
                    step0,
                    start0,
                    input0,
                    0,
                ],
            );
            A::write(p + 0x1f6, 1, result.min(maximum0));
            let freq = if S3 {
                frequency as u16 as usize
            } else {
                frequency as usize
            };
            let value = A::read(p + 0xf3, 1);
            A::external(2, &[value as usize, freq, 0]);
            let n = (A::read(p + 0x1f5, 1) + 1) & 255;
            A::child(2, &[1, p + 0x120, code1, n as usize, out1, 9]);
            if S3 || A::read(p + 0xa2, 1) != 17 {
                let value = A::read(p + 0xf3, 1);
                A::external(2, &[value as usize, freq, 0]);
                let n = (A::read(p + 0x1f6, 1) + 1) & 255;
                A::child(2, &[0, p + 0x120, code0, n as usize, out0, count as usize]);
            }
            let n = (A::read(p + 0x1f5, 1) + 1) & 255;
            A::child(
                1,
                &[
                    1,
                    0,
                    code1,
                    p + if S3 { 0x248 } else { 0x2c4 },
                    p + if S3 { 0x290 } else { 0x30c },
                    p + if S3 { 0x210 } else { 0x21c },
                    n as usize,
                    out1,
                ],
            );
            let n = (A::read(p + 0x1f6, 1) + 1) & 255;
            A::child(
                1,
                &[
                    0,
                    0,
                    code0,
                    p + if S3 { 0x26c } else { 0x2e8 },
                    p + if S3 { 0x290 } else { 0x30c },
                    p + if S3 { 0x210 } else { 0x21c },
                    n as usize,
                    out0,
                ],
            );
            let old = A::read(p + 0x120, 4);
            A::write(p + 0x120, 4, old | 512);
        }
        let value = A::read(p + 0x1f6, 1);
        update::<A>(0x6001c02c, 0xffff80ff, (value & 127) << 8);
        let held0 = A::read(p + 0x1f6, 1);
        update::<A>(0x6001c13c, 0xfe03ffff, held0.min(76) << 18);
        update::<A>(0x6001c0d0, 0xfe01ffff, if S3 { 0xa60000 } else { 0xa00000 });
        update::<A>(0x60011848, 0xff00ffff, if S3 { 0x530000 } else { 0x500000 });
        let held1 = A::read(p + 0x1f5, 1);
        update::<A>(0x6001c0a4, 0xffc07fff, (held1 & 127) << 15);
        for value in [0x800, 0x1000, 0x08000000, 0x10000000] {
            update::<A>(0x6000607c, u32::MAX, value);
        }
        if A::read(p + if S3 { 0x2da } else { 0x34c }, 1) != 0 {
            let value = if S3 { held0 } else { A::read(p + 0x1f6, 1) }.wrapping_sub(5);
            A::write(
                p + 0xd4,
                4,
                value | (value << 8) | (value << 16) | (value << 24),
            );
            let value = if S3 { A::read(p + 0x1f5, 1) } else { held1 }.wrapping_sub(5);
            A::write(
                p + if S3 { 0x2dc } else { 0x344 },
                4,
                value | (value << 8) | (value << 16) | (value << 24),
            );
        }
    }
}

#[cfg(esp32c3)]
pub(crate) const CONSTANTS: [u8; 75] = [
    9, 12, 11, 8, 9, 12, 4, 4, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 1, 3, 6, 3, 12, 11, 10, 0, 0, 0, 0, 0,
    0, 0, 160, 132, 142, 232, 238, 210, 242, 248, 254, 0, 0, 0, 6, 12, 10, 13, 12, 9, 4, 4, 0, 0,
    0, 0, 0, 0, 0, 0, 3, 2, 1, 0, 8, 8, 14, 13, 12, 0, 0, 0, 0, 0, 0,
];
#[cfg(esp32s3)]
pub(crate) const CONSTANTS: [u8; 88] = [
    0, 0, 1, 0, 5, 0, 13, 0, 29, 0, 7, 13, 10, 5, 12, 8, 5, 9, 0, 0, 0, 0, 0, 0, 0, 160, 132, 142,
    232, 238, 210, 242, 248, 254, 160, 132, 134, 226, 232, 208, 244, 248, 254, 7, 9, 8, 5, 8, 12,
    11, 7, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 4, 4, 8, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 4,
    8, 10, 0, 0, 0, 0, 0, 0,
];

#[cfg(not(test))]
mod native {
    use super::{Access, CONSTANTS};
    unsafe extern "C" {
        static mut phy_param: u8;
        static mut g_phyFuns: *const u8;
        fn phy_printf(format: *const u8, ...);
        fn set_rx_gain_cal_iq(a: usize, b: usize, c: usize, d: usize);
        #[cfg(esp32c3)]
        fn set_rx_gain_cal_dc(
            a: usize,
            b: usize,
            c: usize,
            d: usize,
            e: usize,
            f: usize,
            g: usize,
            h: usize,
        );
        #[cfg(esp32s3)]
        fn set_rx_gain_cal_dc(
            a: usize,
            b: usize,
            c: usize,
            d: usize,
            e: usize,
            f: usize,
            g: usize,
            h: usize,
            i: usize,
            j: usize,
        );
        fn set_rf_freq_offset(a: usize, b: usize, c: usize);
        #[cfg(esp32c3)]
        fn rom_phy_reg_init();
    }
    pub(super) struct Native;
    impl Access for Native {
        #[inline(always)]
        unsafe fn param() -> usize {
            (&raw const phy_param) as usize
        }
        #[inline(always)]
        unsafe fn read(a: usize, w: usize) -> u32 {
            unsafe {
                match w {
                    1 => (a as *const u8).read_volatile().into(),
                    2 => (a as *const u16).read_volatile().into(),
                    4 => (a as *const u32).read_volatile(),
                    _ => unreachable!(),
                }
            }
        }
        #[inline(always)]
        unsafe fn write(a: usize, w: usize, v: u32) {
            unsafe {
                match w {
                    1 => (a as *mut u8).write_volatile(v as u8),
                    2 => (a as *mut u16).write_volatile(v as u16),
                    4 => (a as *mut u32).write_volatile(v),
                    _ => unreachable!(),
                }
            }
        }
        #[inline(always)]
        unsafe fn table() -> usize {
            unsafe { (&raw const g_phyFuns).read_volatile() as usize }
        }
        #[inline(always)]
        unsafe fn slot(t: usize, o: usize) -> usize {
            unsafe { ((t + o) as *const usize).read_volatile() }
        }
        #[inline(always)]
        unsafe fn call(t: usize, a: &[u32]) -> u32 {
            unsafe {
                match a.len() {
                    0 => core::mem::transmute::<usize, unsafe extern "C" fn()>(t)(),
                    1 => core::mem::transmute::<usize, unsafe extern "C" fn(u32)>(t)(a[0]),
                    2 => {
                        return core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32) -> u32>(
                            t,
                        )(a[0], a[1]);
                    }
                    3 => core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32, u32)>(t)(
                        a[0], a[1], a[2],
                    ),
                    _ => unreachable!(),
                };
                0
            }
        }
        #[inline(always)]
        unsafe fn external(k: u32, a: &[usize]) {
            unsafe {
                match k {
                    0 => set_rx_gain_cal_iq(a[0], a[1], a[2], a[3]),
                    1 => {
                        #[cfg(esp32c3)]
                        set_rx_gain_cal_dc(a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7]);
                        #[cfg(esp32s3)]
                        set_rx_gain_cal_dc(
                            a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7], a[8], a[9],
                        );
                    }
                    2 => set_rf_freq_offset(a[0], a[1], a[2]),
                    #[cfg(esp32c3)]
                    3 => rom_phy_reg_init(),
                    _ => unreachable!(),
                }
            }
        }
        #[inline(always)]
        unsafe fn log(k: u32, a: &[u32]) {
            unsafe {
                if k == 0 {
                    phy_printf(
                        c"index: %d value: 0x%x 0x%x 0x%x %d %d %d %d\n"
                            .as_ptr()
                            .cast(),
                        a[0],
                        a[1],
                        a[2],
                        a[3],
                        a[4],
                        a[5],
                        a[6],
                        a[7],
                    );
                } else {
                    phy_printf(c"max_gain: %d\n".as_ptr().cast(), a[0]);
                }
            }
        }
        #[inline(always)]
        unsafe fn local(p: *mut u32, _tag: usize, _size: usize) -> usize {
            p as usize
        }
        #[inline(always)]
        unsafe fn copy(d: usize, o: usize, n: usize) {
            unsafe {
                core::ptr::copy_nonoverlapping(CONSTANTS.as_ptr().add(o), d as *mut u8, n);
            }
        }
        #[inline(always)]
        unsafe fn child(k: u32, a: &[usize]) -> u32 {
            unsafe {
                match k {
                    0 => super::__opensensor_rx_gain_generate(
                        a[0], a[1], a[2], a[3], a[4], a[5], a[6],
                    ),
                    1 => {
                        super::__opensensor_rx_gain_write_memory(
                            a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7],
                        );
                        0
                    }
                    2 => {
                        super::__opensensor_rx_gain_set_param(a[0], a[1], a[2], a[3], a[4], a[5]);
                        0
                    }
                    _ => unreachable!(),
                }
            }
        }
    }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_rx_gain_generate(
    a0: usize,
    a1: usize,
    a2: usize,
    a3: usize,
    a4: usize,
    a5: usize,
    a6: usize,
) -> u32 {
    unsafe { generate::<native::Native>(&[a0, a1, a2, a3, a4, a5, a6]) }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_rx_gain_write_memory(
    a0: usize,
    a1: usize,
    a2: usize,
    a3: usize,
    a4: usize,
    a5: usize,
    a6: usize,
    a7: usize,
) {
    unsafe { write_memory::<native::Native>(&[a0, a1, a2, a3, a4, a5, a6, a7]) }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_rx_gain_set_param(
    a0: usize,
    a1: usize,
    a2: usize,
    a3: usize,
    a4: usize,
    a5: usize,
) {
    unsafe { set_param::<native::Native>(&[a0, a1, a2, a3, a4, a5]) }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_rx_gain_set_table(a0: usize, a1: usize) {
    unsafe { set_table::<native::Native>(a0 as u32, a1 as u32) }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_rx_gain_initialize() {
    unsafe { initialize::<native::Native>() }
}
