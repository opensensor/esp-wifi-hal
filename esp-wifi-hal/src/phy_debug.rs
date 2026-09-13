//! IQ conversion and ordered bias/voltage sampling. Calibration policy remains
//! with the caller; these helpers preserve the existing analog callback flow.

pub(crate) trait Access {
    unsafe fn table() -> usize;
    unsafe fn slot(table: usize, offset: usize) -> usize;
    unsafe fn write_iq(destination: usize, offset: usize, value: i8);
    unsafe fn write_mask(target: usize, args: [u32; 6]);
    unsafe fn sample(target: usize, selector: u32) -> u32;
    unsafe fn setup(target: usize);
    unsafe fn mode(target: usize, args: [u32; 3]);
    unsafe fn bias() -> u32;
}

#[cfg(esp32c3)]
const MASK: usize = 0x1bc;
#[cfg(esp32s3)]
const MASK: usize = 0x198;
#[cfg(esp32c3)]
const SAMPLE: usize = 0x150;
#[cfg(esp32s3)]
const SAMPLE: usize = 0x12c;
#[cfg(esp32c3)]
const MODE: usize = 0x1cc;
#[cfg(esp32s3)]
const MODE: usize = 0x1a8;
#[cfg(esp32c3)]
const ENTER: usize = 0x1d4;
#[cfg(esp32s3)]
const ENTER: usize = 0x1b0;
#[cfg(esp32c3)]
const EXIT: usize = 0x1d8;
#[cfg(esp32s3)]
const EXIT: usize = 0x1b4;

#[inline(always)]
unsafe fn function<A: Access>(offset: usize) -> usize {
    unsafe { A::slot(A::table(), offset) }
}

#[inline(always)]
pub(crate) unsafe fn iq<A: Access>(destination: usize, packed: u32, selector: u32) {
    #[cfg(esp32s3)]
    let (packed, selector) = (packed as u16 as u32, selector as u8 as u32);
    let width = if selector == 0 { 5 } else { 6 };
    let first = (((packed >> 6) << (32 - width)) as i32 >> (32 - width)) as i8;
    let second = ((packed << 26) as i32 >> 26) as i8;
    unsafe {
        A::write_iq(destination, 0, first);
        A::write_iq(destination, 1, second);
    }
}

#[inline(always)]
pub(crate) unsafe fn bias<A: Access>() -> u32 {
    unsafe {
        A::write_mask(function::<A>(MASK), [106, 0, 2, 1, 1, 1]);
        A::write_mask(function::<A>(MASK), [106, 0, 7, 3, 2, 1]);
        let result = A::sample(function::<A>(SAMPLE), 3);
        A::write_mask(function::<A>(MASK), [106, 0, 2, 1, 1, 0]);
        A::write_mask(function::<A>(MASK), [106, 0, 7, 3, 2, 0]);
        result
    }
}

#[inline(always)]
pub(crate) unsafe fn voltage<A: Access>() -> u32 {
    unsafe {
        let bias = A::bias();
        A::setup(function::<A>(ENTER));
        A::mode(function::<A>(MODE), [4, 1, 2]);
        A::write_mask(function::<A>(MASK), [107, 0, 9, 7, 7, 1]);
        let sample = A::sample(function::<A>(SAMPLE), 3);
        // Zero bias bypasses both division and narrowing in the original.
        // wrapping_div also preserves signed MIN/-1 without a Rust panic.
        let result = if bias == 0 {
            sample
        } else {
            (sample.wrapping_mul(3840) as i32).wrapping_div(bias as i32) as u16 as u32
        };
        A::write_mask(function::<A>(MASK), [107, 0, 9, 7, 7, 0]);
        A::mode(function::<A>(MODE), [4, 1, 0]);
        A::setup(function::<A>(EXIT));
        result
    }
}

#[cfg(not(test))]
mod native {
    use super::Access;
    unsafe extern "C" {
        static mut g_phyFuns: *const u8;
    }
    pub(super) struct Native;
    impl Access for Native {
        #[inline(always)]
        unsafe fn table() -> usize {
            unsafe { (&raw const g_phyFuns).read_volatile() as usize }
        }
        #[inline(always)]
        unsafe fn slot(table: usize, offset: usize) -> usize {
            unsafe { ((table + offset) as *const usize).read_volatile() }
        }
        #[inline(always)]
        unsafe fn write_iq(destination: usize, offset: usize, value: i8) {
            unsafe { (destination as *mut i8).add(offset).write_volatile(value) }
        }
        #[inline(always)]
        unsafe fn write_mask(target: usize, args: [u32; 6]) {
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32, u32, u32, u32, u32)>(
                    target,
                )(args[0], args[1], args[2], args[3], args[4], args[5])
            }
        }
        #[inline(always)]
        unsafe fn sample(target: usize, selector: u32) -> u32 {
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u32) -> u32>(target)(selector)
            }
        }
        #[inline(always)]
        unsafe fn setup(target: usize) {
            unsafe { core::mem::transmute::<usize, unsafe extern "C" fn()>(target)() }
        }
        #[inline(always)]
        unsafe fn mode(target: usize, args: [u32; 3]) {
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32, u32)>(target)(
                    args[0], args[1], args[2],
                )
            }
        }
        #[inline(always)]
        unsafe fn bias() -> u32 {
            unsafe { super::__opensensor_debug_bias() }
        }
    }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_debug_iq(destination: *mut i8, packed: u32, selector: u32) {
    unsafe { iq::<native::Native>(destination as usize, packed, selector) }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
unsafe extern "C" fn __opensensor_debug_bias() -> u32 {
    unsafe { bias::<native::Native>() }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_debug_voltage() -> u32 {
    unsafe { voltage::<native::Native>() }
}
