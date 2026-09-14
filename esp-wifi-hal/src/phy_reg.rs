//! PHY register programming. Ordered accesses follow the pinned chip binaries.

pub(crate) trait Access {
    unsafe fn param() -> usize;
    unsafe fn read(address: usize, width: usize) -> u32;
    unsafe fn write(address: usize, width: usize, value: u32);
    unsafe fn table() -> usize;
    unsafe fn slot(table: usize, offset: usize) -> usize;
    unsafe fn call(target: usize, args: [u32; 4]);
    unsafe fn internal(kind: u32);
    unsafe fn delay(us: u32);
}
const S3: bool = cfg!(esp32s3);
#[inline(always)]
fn byte_arg(value: u32) -> u32 {
    if S3 { value as u8 as u32 } else { value }
}
#[inline(always)]
unsafe fn update<A: Access>(address: usize, preserve: u32, value: u32) {
    unsafe {
        let old = A::read(address, 4);
        A::write(address, 4, (old & preserve) | value);
    }
}
#[inline(always)]
pub(crate) unsafe fn pbus<A: Access>() {
    unsafe {
        let param = A::param();
        for i in 0..6 {
            let value = A::read(param + if S3 { 0x2ac } else { 0x328 } + i * 4, 4);
            A::write(0x600060e0 + i * 4, 4, value);
        }
    }
}
#[cfg(esp32c3)]
#[inline(always)]
pub(crate) unsafe fn paon<A: Access>() {
    unsafe {
        update::<A>(0x6001d000, 0xffe007ff, 0xa000);
        update::<A>(0x600060f8, 0xffff00ff, 0x9600);
        let _ = A::read(0x6001d06c, 4);
        A::write(0x6001d06c, 4, 0x0782a094);
        update::<A>(0x6001c400, 0xfff8ffff, 0);
    }
}
#[cfg(esp32s3)]
#[inline(always)]
pub(crate) unsafe fn digital_gain<A: Access>(buffer: usize) {
    unsafe {
        for i in 0..3 {
            let b1 = A::read(buffer + i * 4 + 1, 1);
            let b0 = A::read(buffer + i * 4, 1);
            let b2 = A::read(buffer + i * 4 + 2, 1);
            let b3 = A::read(buffer + i * 4 + 3, 1);
            A::write(
                0x60006024 + i * 4,
                4,
                b0 | (b1 << 8) | (b2 << 16) | (b3 << 24),
            );
        }
        let hi = A::read(buffer + 13, 1);
        let lo = A::read(buffer + 12, 1);
        A::write(0x60006030, 4, lo | (hi << 8) | (hi << 16) | (hi << 24));
    }
}
#[inline(always)]
pub(crate) unsafe fn btbb<A: Access>() {
    unsafe {
        update::<A>(0x60026010, u32::MAX, 0xf000b);
    }
}
#[inline(always)]
pub(crate) unsafe fn agc_options<A: Access>() {
    unsafe {
        update::<A>(
            0x6001c1b0,
            0xf01fffff,
            if S3 { 0x04000000 } else { 0x03c00000 },
        );
        if !S3 {
            update::<A>(0x6001c034, 0xffffff80, 32);
        }
        let _ = A::read(0x6001c068, 4);
        A::write(0x6001c068, 4, 0x404);
        update::<A>(0x6001c05c, 0xfff80000, 0x4e20);
        if S3 {
            update::<A>(0x6001c134, 0xfffff000, 0xa60);
            update::<A>(0x6001c134, 0xf8ffffff, 0x05000000);
        } else {
            let p = A::param();
            let value = A::read(p + 0x1f6, 1).wrapping_sub(3);
            update::<A>(0x6001c13c, 0xfe03ffff, (value << 18) & 0x01fc0000);
            let value = A::read(p + 0x1f6, 1).wrapping_sub(3);
            update::<A>(0x6001c094, 0xfffffe03, (value << 2) & 0x1fc);
            let threshold = A::read(p + 0x1f6, 1).wrapping_sub(5);
            let value = A::read(p + 0x1f5, 1);
            A::write(0x6001c0a4, 4, (value << 15) | threshold | (threshold << 7));
        }
    }
}
#[inline(always)]
pub(crate) unsafe fn options_11b<A: Access>(mode: u32) {
    unsafe {
        let old = A::read(0x6001c044, 4);
        let enabled = byte_arg(mode) != 0;
        A::write(
            0x6001c044,
            4,
            if enabled {
                old | 0x003f0000
            } else {
                (old & 0xffc0ffff) | 0x003e0000
            },
        );
        update::<A>(
            0x6001c044,
            0xffffc0ff,
            if enabled { 0x2100 } else { 0x1800 },
        );
        update::<A>(
            0x6001c124,
            0xffff03ff,
            if enabled { 0x8400 } else { 0x6000 },
        );
        update::<A>(0x6001c124, 0xfffffff0, if enabled { 3 } else { 4 });
        update::<A>(
            0x6001c804,
            0xffff0fff,
            if enabled { 0x9000 } else { 0x6000 },
        );
        update::<A>(0x6001c104, 0xfffffe00, if enabled { 482 } else { 456 });
        update::<A>(0x60026010, u32::MAX, 0x20000);
        if !S3 {
            A::internal(2);
        }
        A::internal(3);
    }
}
#[inline(always)]
pub(crate) unsafe fn disable_agc<A: Access>() {
    unsafe {
        update::<A>(0x6001c01c, 0xff00ffff, 0x007f0000);
        update::<A>(0x6001c034, u32::MAX, 128);
        update::<A>(0x6001c080, u32::MAX, 1);
    }
}
#[inline(always)]
pub(crate) unsafe fn enable_agc<A: Access>() {
    unsafe {
        update::<A>(0x6001c080, 0xfffffffe, 0);
        update::<A>(0x6001c01c, 0xff00ffff, 0x00200000);
        update::<A>(0x6001c034, u32::MAX, 128);
    }
}
#[inline(always)]
pub(crate) unsafe fn renew<A: Access>() {
    unsafe {
        update::<A>(0x6000e058, 0xffffff00, if S3 { 100 } else { 64 });
        update::<A>(0x6000e060, 0xffff00ff, if S3 { 0x5000 } else { 0x3800 });
        update::<A>(0x60006000, u32::MAX, 1 << 26);
        update::<A>(0x60006000, u32::MAX, 1 << 27);
        update::<A>(0x6000e048, 0xfffe000f, 0x1fe00);
        if S3 {
            update::<A>(0x600060fc, 0xffff00ff, 0xc800);
            A::internal(2);
            let target = A::slot(A::table(), 0x190);
            let value = A::read(A::param() + 0x2a1, 1);
            A::call(target, [102, 0, 5, value]);
        } else {
            let p = A::param();
            for i in 0..2 {
                let table = A::table();
                let value = A::read(p + 0x31d + i, 1);
                let target = A::slot(table, 0x1b4);
                A::call(target, [102, 0, 4 + i as u32, value]);
            }
            update::<A>(0x600060fc, 0xffff, 0x1e1e0000);
            update::<A>(0x600060fc, 0xffff00ff, 0xc800);
        }
    }
}
#[inline(always)]
pub(crate) unsafe fn wifi_enable<A: Access>(mode: u32) {
    unsafe {
        update::<A>(
            0x6002600c,
            0xfffffffd,
            if byte_arg(mode) != 0 { 2 } else { 0 },
        );
    }
}
/// Preserve the machine result register, including S3's zero-extended low byte.
#[inline(always)]
pub(crate) unsafe fn tx_iq<A: Access>(coefficient: u32, mode: u32) -> u32 {
    unsafe {
        let mode = byte_arg(mode);
        let value = if S3 {
            coefficient as i8 as i32
        } else {
            coefficient as i32
        };
        let bound = if mode == 0 { 31 } else { 15 };
        let value = value.clamp(-bound, bound);
        if mode == 0 {
            update::<A>(0x6000607c, !0x7e0, ((value as u32) << 5) & 0x7e0);
        } else {
            update::<A>(0x6000607c, !31, (value as u32) & 31);
        }
        if S3 { value as u8 as u32 } else { value as u32 }
    }
}
#[inline(always)]
pub(crate) unsafe fn rx_iq<A: Access>(coefficient: u32, mode: u32) -> u32 {
    unsafe {
        let mode = byte_arg(mode);
        let value = if S3 {
            coefficient as i8 as i32
        } else {
            coefficient as i32
        };
        let value = if mode == 0 {
            value.clamp(-31, 31)
        } else {
            (value / 2).clamp(-15, 15)
        };
        let result = if mode == 0 {
            update::<A>(0x6000607c, !0x07e00000, ((value as u32) << 21) & 0x07e00000);
            value
        } else {
            update::<A>(0x6000607c, !0x001f0000, ((value as u32) << 16) & 0x001f0000);
            value * 2
        };
        if S3 {
            result as u8 as u32
        } else {
            result as u32
        }
    }
}
#[inline(always)]
pub(crate) unsafe fn start_tone<A: Access>(a: [u32; 6]) {
    unsafe {
        let divided = A::read(0x60006040, 4) & (1 << 29) != 0;
        let (en0, en1) = (byte_arg(a[0]), byte_arg(a[3]));
        let (mut f0, mut f1) = if S3 {
            (a[1] as i16 as i32, a[4] as i16 as i32)
        } else {
            (a[1] as i32, a[4] as i32)
        };
        let (p0, p1) = (a[2].wrapping_neg() & 255, a[5].wrapping_neg() & 255);
        if en0 | en1 != 0 {
            update::<A>(0x60006000, !(1 << 26), 0);
            update::<A>(0x600061e4, u32::MAX, 1 << 10);
        } else {
            update::<A>(0x60006000, u32::MAX, 1 << 26);
            update::<A>(0x600061e4, !(1 << 10), 0);
        }
        if divided {
            update::<A>(0x60006050, !3, (f0 as u32) & 3);
            update::<A>(0x60006050, !12, ((f1 as u32) << 2) & 12);
            f0 >>= 2;
            f1 >>= 2;
        }
        update::<A>(
            0x60006040,
            0xf0000000,
            ((en0 << 18) | (p0 << 10) | (f0 as u32)) & 0x0fffffff,
        );
        update::<A>(
            0x60006044,
            0xf0000000,
            ((en1 << 18) | (p1 << 10) | (f1 as u32)) & 0x0fffffff,
        );
    }
}
#[inline(always)]
pub(crate) unsafe fn stop_tone<A: Access>(mode: u32) {
    unsafe {
        match mode {
            1 => update::<A>(0x60006040, !(1 << 18), 0),
            2 => update::<A>(0x60006044, !(1 << 18), 0),
            3 => update::<A>(0x6000604c, !(1 << 18), 0),
            _ => {
                update::<A>(0x60006040, !(1 << 18), 0);
                update::<A>(0x60006044, !(1 << 18), 0);
                update::<A>(0x6000604c, !(1 << 18), 0);
            }
        }
        update::<A>(0x60006000, u32::MAX, 1 << 26);
        update::<A>(0x600061e4, !(1 << 10), 0);
    }
}
#[inline(always)]
pub(crate) unsafe fn noise_floor<A: Access>() {
    unsafe {
        if !S3 {
            update::<A>(0x6001c134, 0xfffff00f, 0xa60);
        }
    }
}
#[inline(always)]
pub(crate) unsafe fn frequency_correct<A: Access>(mode: u32, offset: u32) {
    unsafe {
        if byte_arg(mode) != 0 {
            let offset = if S3 {
                offset as i16 as i32
            } else {
                offset as i32
            };
            let twice = offset.wrapping_mul(2);
            let q = twice / 5;
            update::<A>(0x6001d030, !1023, 250);
            update::<A>(0x60006090, !511, 250);
            update::<A>(0x60006070, !(1 << 30), 0);
            update::<A>(0x60006064, 0xfff00000, 0xf4240);
            update::<A>(0x60006068, 0xfff00000, 0xf4240u32.wrapping_add(q as u32));
            let (value, threshold) = if S3 { (q, 100) } else { (twice, 504) };
            let field = if value > threshold {
                2
            } else if value < -threshold {
                61
            } else {
                31
            };
            update::<A>(0x6001c850, 0xffff81ff, field << 9);
            update::<A>(0x6001c850, !511, (q as u32) & 511);
            update::<A>(0x6001cc98, !1023, (q as u32) & 1023);
        } else {
            update::<A>(0x6001d030, !1023, 0);
            update::<A>(0x60006090, !511, 0);
            update::<A>(0x60006070, u32::MAX, 1 << 30);
            update::<A>(0x6001c850, 0xffff81ff, 31 << 9);
            update::<A>(0x6001c850, !511, 0);
            update::<A>(0x6001cc98, !1023, 0);
        }
    }
}
#[inline(always)]
pub(crate) unsafe fn force_off<A: Access>(mode: u32) {
    unsafe {
        let enabled = byte_arg(mode) != 0;
        update::<A>(0x60006110, 0xfffff0ff, if enabled { 0x800 } else { 0x200 });
        A::delay(1);
        update::<A>(0x60006110, 0xfffff0ff, if enabled { 0xa00 } else { 0 });
        A::delay(1);
    }
}

#[cfg(not(test))]
mod native {
    use super::Access;
    unsafe extern "C" {
        static mut phy_param: u8;
        static mut g_phyFuns: *const u8;
        fn ets_delay_us(us: u32);
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
        unsafe fn call(t: usize, a: [u32; 4]) {
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32, u32, u32)>(t)(
                    a[0], a[1], a[2], a[3],
                );
            }
        }
        #[inline(always)]
        unsafe fn internal(k: u32) {
            unsafe {
                match k {
                    2 => super::__opensensor_reg_btbb(),
                    3 => super::__opensensor_reg_agc_options(),
                    _ => unreachable!(),
                }
            }
        }
        #[inline(always)]
        unsafe fn delay(us: u32) {
            unsafe {
                ets_delay_us(us);
            }
        }
    }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
#[unsafe(link_section = ".rwtext")]
pub unsafe extern "C" fn __opensensor_reg_pbus() {
    unsafe { pbus::<native::Native>() }
}

#[cfg(not(test))]
#[cfg(esp32c3)]
#[unsafe(no_mangle)]
#[inline(never)]
#[unsafe(link_section = ".rwtext")]
pub unsafe extern "C" fn __opensensor_reg_paon() {
    unsafe { paon::<native::Native>() }
}

#[cfg(not(test))]
#[cfg(esp32s3)]
#[unsafe(no_mangle)]
#[inline(never)]
#[unsafe(link_section = ".rwtext")]
pub unsafe extern "C" fn __opensensor_reg_digital_gain(a0: u32) {
    unsafe { digital_gain::<native::Native>(a0 as usize) }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
#[unsafe(link_section = ".rwtext")]
pub unsafe extern "C" fn __opensensor_reg_btbb() {
    unsafe { btbb::<native::Native>() }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
#[unsafe(link_section = ".rwtext")]
pub unsafe extern "C" fn __opensensor_reg_agc_options() {
    unsafe { agc_options::<native::Native>() }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
#[unsafe(link_section = ".rwtext")]
pub unsafe extern "C" fn __opensensor_reg_options_11b(a0: u32) {
    unsafe { options_11b::<native::Native>(a0) }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
#[unsafe(link_section = ".rwtext")]
pub unsafe extern "C" fn __opensensor_reg_disable_agc() {
    unsafe { disable_agc::<native::Native>() }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
#[unsafe(link_section = ".rwtext")]
pub unsafe extern "C" fn __opensensor_reg_enable_agc() {
    unsafe { enable_agc::<native::Native>() }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
#[unsafe(link_section = ".rwtext")]
pub unsafe extern "C" fn __opensensor_reg_renew() {
    unsafe { renew::<native::Native>() }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
#[unsafe(link_section = ".rwtext")]
pub unsafe extern "C" fn __opensensor_reg_wifi_enable(a0: u32) {
    unsafe { wifi_enable::<native::Native>(a0) }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_reg_tx_iq(a0: u32, a1: u32) -> u32 {
    unsafe { tx_iq::<native::Native>(a0, a1) }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_reg_rx_iq(a0: u32, a1: u32) -> u32 {
    unsafe { rx_iq::<native::Native>(a0, a1) }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_reg_start_tone(
    a0: u32,
    a1: u32,
    a2: u32,
    a3: u32,
    a4: u32,
    a5: u32,
) {
    unsafe { start_tone::<native::Native>([a0, a1, a2, a3, a4, a5]) }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_reg_stop_tone(a0: u32) {
    unsafe { stop_tone::<native::Native>(a0) }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_reg_noise_floor() {
    unsafe { noise_floor::<native::Native>() }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_reg_frequency_correct(a0: u32, a1: u32) {
    unsafe { frequency_correct::<native::Native>(a0, a1) }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_reg_force_off(a0: u32) {
    unsafe { force_off::<native::Native>(a0) }
}
