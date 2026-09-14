//! Hardware frequency memory, I2C tables and channel-switch sequencing.

pub(crate) trait Access {
    unsafe fn param() -> usize;
    unsafe fn read(address: usize, width: usize) -> u32;
    unsafe fn write(address: usize, width: usize, value: u32);
    unsafe fn table() -> usize;
    unsafe fn slot(table: usize, offset: usize) -> usize;
    unsafe fn read_call<const N: usize>(target: usize, args: [u32; N]) -> u32;
    unsafe fn write_call<const N: usize>(target: usize, args: [u32; N]);
    unsafe fn external<const N: usize>(kind: u32, args: [u32; N]) -> u32;
    unsafe fn internal<const N: usize>(kind: u32, args: [u32; N]);
    unsafe fn scratch<F: FnOnce(usize)>(kind: u32, f: F);
    unsafe fn local_read(address: usize, width: usize) -> u32;
    unsafe fn local_write(address: usize, width: usize, value: u32);
}
const S3: bool = cfg!(esp32s3);
const CONTROL: usize = 0x6000e0c4;
const READ: usize = if S3 { 0x188 } else { 0x1ac };
const MASK_READ: usize = READ + 12;
const MASK_WRITE: usize = READ + 16;
#[inline(always)]
unsafe fn target<A: Access>(slot: usize) -> usize {
    unsafe { A::slot(A::table(), slot) }
}
#[inline(always)]
unsafe fn update<A: Access>(address: usize, mask: u32, value: u32) {
    unsafe {
        let old = A::read(address, 4);
        A::write(address, 4, (old & !mask) | value);
    }
}
#[inline(always)]
fn short(value: u32) -> u32 {
    value as i16 as i32 as u32
}
#[inline(always)]
pub(crate) unsafe fn wait<A: Access>() {
    unsafe { while A::read(0x6000e168, 4) & 0x80000000 != 0 {} }
}
#[inline(always)]
pub(crate) unsafe fn disable<A: Access>() {
    unsafe {
        update::<A>(CONTROL, 0, 0x02000000);
        A::external(0, [2]);
    }
}
#[inline(always)]
pub(crate) unsafe fn enable<A: Access>() {
    unsafe {
        update::<A>(CONTROL, 0x02000000, 0);
    }
}
#[inline(always)]
pub(crate) unsafe fn memory<A: Access>(index: u32, buffer: usize) {
    unsafe {
        for i in 0..3 {
            let (value, old) = if S3 {
                let old = A::read(CONTROL, 4);
                (A::read(buffer + i * 4, 4), old)
            } else {
                let value = A::read(buffer + i * 4, 4);
                (value, A::read(CONTROL, 4))
            };
            A::write(
                CONTROL,
                4,
                (old & !255) | (index.wrapping_mul(3).wrapping_add(i as u32) & 255),
            );
            A::write(0x6000e148, 4, value);
            update::<A>(CONTROL, 0, 0x200);
            update::<A>(CONTROL, 0x200, 0);
        }
    }
}
/// Buffer order follows the nine-argument vendor ABI: host, block, register,
/// first selector/value, second selector/value, count, enabled.
#[inline(always)]
pub(crate) unsafe fn write_i2c<A: Access>(p: [usize; 8], count: u32) {
    unsafe {
        let count = if S3 { count as u8 as u32 } else { count };
        update::<A>(CONTROL, 0x7c00, (count << 10) & 0x7c00);
        let mut mask = 0u32;
        let mut i = 0u32;
        while (i as u8 as u32) < count {
            if A::read(p[7] + i as usize, 1) == 1 {
                mask = mask.wrapping_add(1u32.wrapping_shl(i));
            }
            i = i.wrapping_add(1);
        }
        A::write(0x6000e164, 4, mask);
        i = 0;
        while (i as u8 as u32) < count {
            let bank = (i as u8 as u32) >> 3;
            let address = match bank {
                0 => 0x6000e100,
                1 => 0x6000e104,
                _ => 0x6000e108,
            };
            let shift = i.wrapping_mul(4) & 31;
            let (value, old) = if S3 && bank == 0 {
                let old = A::read(address, 4);
                (A::read(p[0] + i as usize, 1), old)
            } else {
                let value = A::read(p[0] + i as usize, 1);
                (value, A::read(address, 4))
            };
            A::write(address, 4, (old & !(15 << shift)) | ((value & 15) << shift));
            i = i.wrapping_add(1);
        }
        i = 0;
        while (i as u8 as u32) < count {
            let bank = (i as u8 as u32) >> 1;
            let address = match bank {
                0..=7 => 0x6000e0d8 + bank as usize * 4,
                8 => 0x6000e10c,
                _ => 0x6000e110,
            };
            let (value, old) = if S3 && bank >= 7 {
                let block = A::read(p[1] + i as usize, 1);
                let old = A::read(address, 4);
                ((A::read(p[2] + i as usize, 1) << 8) | block, old)
            } else {
                let reg = A::read(p[2] + i as usize, 1);
                let block = A::read(p[1] + i as usize, 1);
                ((reg << 8) | block, A::read(address, 4))
            };
            let shift = (i & 1) * 16;
            A::write(address, 4, (old & !(65535 << shift)) | (value << shift));
            i = i.wrapping_add(1);
        }
        i = 0;
        while (i as u8 as u32) < count {
            let second = A::read(p[5] + i as usize, 1);
            update::<A>(
                0x6000e128,
                1u32.wrapping_shl(i),
                ((second >> 4) & 1).wrapping_shl(i),
            );
            let first = A::read(p[3] + i as usize, 1);
            update::<A>(
                0x6000e12c,
                1u32.wrapping_shl(i),
                ((first >> 4) & 1).wrapping_shl(i),
            );
            let bank = (i as u8 as u32) >> 3;
            let shift = (i * 4) & 31;
            let (second_address, first_address) = match bank {
                0 => (0x6000e0d0, 0x6000e11c),
                1 => (0x6000e0d4, 0x6000e120),
                _ => (0x6000e124, 0x6000e124),
            };
            let second = A::read(p[5] + i as usize, 1);
            update::<A>(second_address, 15 << shift, (second & 15) << shift);
            let first_shift = if bank >= 2 { (shift + 16) & 31 } else { shift };
            let (first, old) = if S3 && bank == 0 {
                let old = A::read(first_address, 4);
                (A::read(p[3] + i as usize, 1), old)
            } else {
                let first = A::read(p[3] + i as usize, 1);
                (first, A::read(first_address, 4))
            };
            A::write(
                first_address,
                4,
                (old & !(15 << first_shift)) | ((first & 15) << first_shift),
            );
            i = i.wrapping_add(1);
        }
        i = 0;
        while (i as u8 as u32) < count {
            for (selector, data) in [(5, 6), (3, 4)] {
                let slot = A::read(p[selector] + i as usize, 1);
                let address = match slot >> 2 {
                    0 => 0x6000e0c8,
                    1 => 0x6000e0cc,
                    2 => 0x6000e114,
                    3 => 0x6000e118,
                    _ => continue,
                };
                let shift = (slot & 3) * 8;
                let old = A::read(address, 4);
                let value = A::read(p[data] + i as usize, 1);
                A::write(address, 4, (old & !(255 << shift)) | (value << shift));
            }
            i = i.wrapping_add(1);
        }
    }
}
#[inline(always)]
pub(crate) unsafe fn cap_memory<A: Access>(delta: u32) {
    unsafe {
        for i in 0..85 {
            update::<A>(CONTROL, 255, i * 3);
            let old = A::read(0x6000e0c0, 4);
            let cap = ((old & 255) | ((old >> 4) & 256)).wrapping_add(delta) as u16;
            A::write(
                0x6000e148,
                4,
                (old & 0xef00)
                    | u32::from(cap as u8)
                    | (((i32::from(cap as i16) >> 8) as u32) << 12),
            );
            update::<A>(CONTROL, 0, 0x200);
            update::<A>(CONTROL, 0x200, 0);
        }
    }
}
#[inline(always)]
pub(crate) unsafe fn initialize<A: Access>() {
    unsafe {
        let param = A::param();
        if A::read(param + 0x120, 4) & 32 != 0 {
            return;
        }
        A::scratch(0, |buffer| {
            if S3 {
                A::write_call(target::<A>(0x20c), [200]);
            } else {
                A::external(1, [200]);
            }
            A::write_call(target::<A>(MASK_WRITE), [98, 1, 2, 7, 7, 0]);
            let selector = A::read(param + 0xf3, 1);
            A::external(2, [selector, 2437, 0, buffer as u32]);
            let saved = A::read_call(target::<A>(MASK_READ), [98, 1, 6, 3, 0]);
            A::write_call(target::<A>(MASK_WRITE), [98, 1, 2, 3, 0, saved]);
            A::write_call(target::<A>(MASK_WRITE), [98, 1, 2, 7, 7, 1]);
            let selector = A::read(param + 0xf3, 1);
            A::external(2, [selector, 2400, 0, buffer as u32]);
            let low = A::external(3, []);
            let selector = A::read(param + 0xf3, 1);
            A::external(2, [selector, 2464, 0, buffer as u32]);
            let high = A::external(3, []);
            let delta = (high as i16 as i32) - (low as i16 as i32);
            let mut accumulated = 0i32;
            for i in 0..85 {
                let selector = A::read(param + 0xf3, 1);
                A::external(4, [2400 + i, selector, 0, buffer as u32]);
                let cap = A::read_call(
                    target::<A>(0x28),
                    [short(low.wrapping_add((accumulated / 64) as u32)), 511, 0],
                );
                let first = (((short(cap) as i32 >> 8) as u32) << 4) | saved | 0xffffff80;
                let b0 = A::local_read(buffer, 1);
                let b1 = A::local_read(buffer + 1, 1);
                let b2 = A::local_read(buffer + 2, 1);
                A::local_write(buffer + 4, 4, ((first & 255) << 8) | (cap & 255));
                A::local_write(buffer + 8, 4, (b0 << 16) | (b1 << 8) | b2);
                A::local_write(buffer + 12, 4, 0);
                A::internal(3, [i, (buffer + 4) as u32]);
                accumulated = accumulated.wrapping_add(delta);
            }
            let flags = A::read(param + 0x120, 4);
            if !S3 {
                A::write(param + 0xe2, 2, 0);
            }
            A::write(param + 0x120, 4, flags | 32);
            if S3 {
                A::write(param + 0xe2, 2, 0);
            }
        });
    }
}
#[inline(always)]
pub(crate) unsafe fn read_i2c<A: Access>(p: [usize; 8], count: u32) {
    unsafe {
        let count = if S3 { count as u8 as u32 } else { count };
        A::write_call(target::<A>(MASK_WRITE), [98, 1, 11, 6, 6, 1]);
        let cap = A::read_call(target::<A>(READ), [98, 1, 11]);
        let sdm = A::read_call(target::<A>(READ), [99, 1, 0]);
        A::write_call(
            target::<A>(if S3 { 0x100 } else { 0x114 }),
            [(A::param() + 0x158) as u32, 6],
        );
        let mut i = 0u32;
        while (i as u8 as u32) < count {
            let index = i as usize;
            A::write(p[7] + index, 1, 0);
            let (host, block, register, first, second, first_value, second_value) = match i {
                0 => (1, 99, 0, 15, 15, 0, 0),
                1 => (1, 98, 1, 16, 16, 0, 0),
                2 => (1, 98, 2, 17, 17, 0, 0),
                3 => (1, 99, 0, 0, 0, sdm & 239, sdm & 239),
                4 => (1, 99, 3, 22, 22, 0, 0),
                5 => (1, 99, 5, 20, 20, 0, 0),
                6 => (1, 99, 4, 21, 21, 0, 0),
                7 => (1, 99, 0, 1, 1, (sdm | 16) & 255, (sdm | 16) & 255),
                8 => (1, 98, 11, 2, 2, cap, cap),
                9 => (if S3 { 0 } else { 1 }, 103, 3, 3, 4, 240, 244),
                _ => {
                    i = i.wrapping_add(1);
                    continue;
                }
            };
            for (array, value) in [
                (0, host),
                (1, block),
                (2, register),
                (3, first),
                (5, second),
                (4, first_value),
                (6, second_value),
            ] {
                A::write(p[array] + index, 1, value);
            }
            if i == 0 {
                A::write(p[7], 1, 1);
            }
            i = i.wrapping_add(1);
        }
    }
}
#[inline(always)]
pub(crate) unsafe fn program_i2c<A: Access>() {
    unsafe {
        A::scratch(1, |buffer| {
            let a = core::array::from_fn::<u32, 9, _>(|i| {
                if i == 7 {
                    10
                } else {
                    (buffer + (if i == 8 { 7 } else { i }) * 10) as u32
                }
            });
            A::internal(7, a);
            A::internal(4, a);
        });
    }
}
#[inline(always)]
pub(crate) unsafe fn hardware_init<A: Access>(first: u32, second: u32) {
    unsafe {
        let bias = A::external(5, []);
        A::write(A::param() + 0xde, 2, bias);
        A::internal(6, []);
        A::internal(8, []);
        update::<A>(0x6003509c, 0xffff0000, 0x0c800000);
        update::<A>(CONTROL, 0x000f0000, (first << 16) & 0x000f0000);
        update::<A>(CONTROL, 0x00f00000, (second << 20) & 0x00f00000);
        update::<A>(CONTROL, 0, 0x01000000);
        update::<A>(CONTROL, 0, 0x40000000);
        update::<A>(CONTROL, 0x20000000, 0);
    }
}
#[inline(always)]
pub(crate) unsafe fn software_start<A: Access>(channel: u32, offset: u32, mode: u32) {
    unsafe {
        let channel = if S3 { channel as u8 as u32 } else { channel };
        update::<A>(CONTROL, 256, 0);
        A::external(
            6,
            [
                if S3 { short(offset) } else { offset },
                if S3 { mode as u8 as u32 } else { mode },
                (A::param() + 0xe2) as u32,
            ],
        );
        update::<A>(0x6000e150, 0x0ff00000, channel << 20);
        update::<A>(CONTROL, 255, (channel << 1) & 255);
        for _ in 0..3 {
            wait::<A>();
            update::<A>(CONTROL, 0, 256);
            update::<A>(CONTROL, 256, 0);
            A::external(0, [1]);
            wait::<A>();
            if (A::read(0x6000e170, 4) >> 17) & 127 == channel {
                break;
            }
        }
        let cap = A::external(3, []);
        A::write(A::param() + if S3 { 0x2aa } else { 0x326 }, 2, cap);
    }
}

#[cfg(not(test))]
mod native {
    use super::Access;
    unsafe extern "C" {
        static mut phy_param: u8;
        static mut g_phyFuns: *const u8;
        fn ets_delay_us(us: u32);
        #[cfg(esp32c3)]
        fn rom2_write_pll_cap(value: u32);
        fn set_rfpll_freq(selector: u32, frequency: u32, offset: u32, buffer: u32);
        #[cfg_attr(esp32c3, link_name = "rom2_read_pll_cap")]
        #[cfg_attr(esp32s3, link_name = "read_pll_cap")]
        fn read_cap() -> u32;
        fn rfpll_set_freq(frequency: u32, selector: u32, offset: u32, buffer: u32);
        fn get_bias_ref_code() -> u32;
        fn correct_rfpll_offset(offset: u32, mode: u32, stored: u32);
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
                    1 => core::mem::transmute::<usize, unsafe extern "C" fn(u32)>(target)(a[0]),
                    2 => core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32)>(target)(
                        a[0], a[1],
                    ),
                    6 => core::mem::transmute::<
                        usize,
                        unsafe extern "C" fn(u32, u32, u32, u32, u32, u32),
                    >(target)(a[0], a[1], a[2], a[3], a[4], a[5]),
                    _ => unreachable!(),
                }
            }
        }
        #[inline(always)]
        unsafe fn external<const N: usize>(kind: u32, a: [u32; N]) -> u32 {
            unsafe {
                match kind {
                    0 => {
                        ets_delay_us(a[0]);
                        0
                    }
                    #[cfg(esp32c3)]
                    1 => {
                        rom2_write_pll_cap(a[0]);
                        0
                    }
                    2 => {
                        set_rfpll_freq(a[0], a[1], a[2], a[3]);
                        0
                    }
                    3 => read_cap(),
                    4 => {
                        rfpll_set_freq(a[0], a[1], a[2], a[3]);
                        0
                    }
                    5 => get_bias_ref_code(),
                    6 => {
                        correct_rfpll_offset(a[0], a[1], a[2]);
                        0
                    }
                    _ => unreachable!(),
                }
            }
        }
        #[inline(always)]
        unsafe fn scratch<F: FnOnce(usize)>(_kind: u32, f: F) {
            let mut buffer = core::mem::MaybeUninit::<[u32; 20]>::uninit();
            f(buffer.as_mut_ptr() as usize);
        }
        #[inline(always)]
        unsafe fn local_read(address: usize, width: usize) -> u32 {
            unsafe { Self::read(address, width) }
        }
        #[inline(always)]
        unsafe fn local_write(address: usize, width: usize, value: u32) {
            unsafe {
                Self::write(address, width, value);
            }
        }
        #[inline(always)]
        unsafe fn internal<const N: usize>(kind: u32, a: [u32; N]) {
            unsafe {
                match kind {
                    3 => super::__opensensor_hw_freq_memory(a[0], a[1]),
                    4 => super::__opensensor_hw_freq_write_i2c(
                        a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7], a[8],
                    ),
                    6 => super::__opensensor_hw_freq_initialize(),
                    7 => super::__opensensor_hw_freq_read_i2c(
                        a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7], a[8],
                    ),
                    8 => super::__opensensor_hw_freq_program_i2c(),
                    _ => unreachable!(),
                }
            }
        }
    }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
#[unsafe(link_section = ".rwtext")]
pub unsafe extern "C" fn __opensensor_hw_freq_wait() {
    unsafe {
        wait::<native::Native>();
    }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
#[unsafe(link_section = ".rwtext")]
pub unsafe extern "C" fn __opensensor_hw_freq_disable() {
    unsafe {
        disable::<native::Native>();
    }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
#[unsafe(link_section = ".rwtext")]
pub unsafe extern "C" fn __opensensor_hw_freq_enable() {
    unsafe {
        enable::<native::Native>();
    }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_hw_freq_memory(a0: u32, a1: u32) {
    unsafe {
        memory::<native::Native>(a0, a1 as usize);
    }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_hw_freq_write_i2c(
    a0: u32,
    a1: u32,
    a2: u32,
    a3: u32,
    a4: u32,
    a5: u32,
    a6: u32,
    a7: u32,
    a8: u32,
) {
    unsafe {
        write_i2c::<native::Native>(
            [
                a0 as usize,
                a1 as usize,
                a2 as usize,
                a3 as usize,
                a4 as usize,
                a5 as usize,
                a6 as usize,
                a8 as usize,
            ],
            a7,
        );
    }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_hw_freq_cap_memory(a0: u32) {
    unsafe {
        cap_memory::<native::Native>(a0);
    }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_hw_freq_initialize() {
    unsafe {
        initialize::<native::Native>();
    }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_hw_freq_read_i2c(
    a0: u32,
    a1: u32,
    a2: u32,
    a3: u32,
    a4: u32,
    a5: u32,
    a6: u32,
    a7: u32,
    a8: u32,
) {
    unsafe {
        read_i2c::<native::Native>(
            [
                a0 as usize,
                a1 as usize,
                a2 as usize,
                a3 as usize,
                a4 as usize,
                a5 as usize,
                a6 as usize,
                a8 as usize,
            ],
            a7,
        );
    }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_hw_freq_program_i2c() {
    unsafe {
        program_i2c::<native::Native>();
    }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_hw_freq_hardware_init(a0: u32, a1: u32) {
    unsafe {
        hardware_init::<native::Native>(a0, a1);
    }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_hw_freq_software_start(a0: u32, a1: u32, a2: u32) {
    unsafe {
        software_start::<native::Native>(a0, a1, a2);
    }
}
