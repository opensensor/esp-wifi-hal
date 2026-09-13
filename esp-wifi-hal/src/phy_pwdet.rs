//! Power-detector sequencing and arithmetic. ROM ADC/conversion callbacks and
//! the caller's calibration policy remain dependencies.
use core::mem::MaybeUninit;

pub(crate) trait Access {
    unsafe fn param() -> usize;
    unsafe fn read16(address: usize) -> u16;
    unsafe fn write16(address: usize, value: u16);
    unsafe fn read32(address: usize) -> u32;
    unsafe fn write32(address: usize, value: u32);
    unsafe fn table() -> usize;
    unsafe fn slot(table: usize, offset: usize) -> usize;
    unsafe fn setup(target: usize);
    unsafe fn fill(target: usize, output: &mut MaybeUninit<[u16; 8]>);
    unsafe fn convert(target: usize, value: i32, selector: u32) -> u32;
    unsafe fn delay(microseconds: u32);
    unsafe fn tone();
    unsafe fn samples(count: u32) -> u32;
    unsafe fn reference(input: u32, signal: usize, reference: usize);
    unsafe fn fm(signal: usize, reference: usize) -> u32;
    unsafe fn divide_unsigned(numerator: u32, denominator: u32) -> u32;
}

#[cfg(esp32c3)]
const SETUP: usize = 0x144;
#[cfg(esp32s3)]
const SETUP: usize = 0x120;
#[cfg(esp32c3)]
const OUTPUT: usize = 0x148;
#[cfg(esp32s3)]
const OUTPUT: usize = 0x124;
#[cfg(esp32c3)]
const CONVERT: usize = 0x118;
#[cfg(esp32s3)]
const CONVERT: usize = 0x104;

// The retained ROM output callback writes eight consecutive halfwords. Keep
// the original stack alignment, even though only the second sample is read.
#[repr(C, align(16))]
struct Samples(MaybeUninit<[u16; 8]>);

#[inline(always)]
pub(crate) fn power() {}

#[inline(always)]
unsafe fn function<A: Access>(offset: usize) -> usize {
    unsafe { A::slot(A::table(), offset) }
}

#[inline(always)]
pub(crate) unsafe fn reference<A: Access>(input: u32, signal: usize, reference: usize) {
    unsafe {
        let param = A::param();
        let baseline = A::read16(param + 0xda);
        let calibrated = A::read16(param + 0xdc);
        let input = input.wrapping_add(if cfg!(esp32c3) { 40 } else { 50 }) as u16;
        // Both parameter reads precede either output store, including aliases.
        A::write16(
            signal,
            if input >= baseline {
                input.wrapping_sub(baseline)
            } else {
                0
            },
        );
        A::write16(
            reference,
            if calibrated >= baseline {
                calibrated.wrapping_sub(baseline)
            } else {
                0
            },
        );
    }
}

#[inline(always)]
unsafe fn modify<A: Access>(address: usize, clear: u32, set: u32) {
    unsafe { A::write32(address, (A::read32(address) & !clear) | set) }
}

#[inline(always)]
unsafe fn wait_ready<A: Access>() {
    // Preserve the original polling operation; readiness belongs to hardware.
    while unsafe { (A::read32(0x6000e050) >> 24) & 7 } != 7 {}
}

#[inline(always)]
pub(crate) unsafe fn tone<A: Access>() {
    unsafe {
        modify::<A>(0x60006040, 0, 1 << 18);
        A::delay(1);
        modify::<A>(0x6000e050, 2, 0);
        modify::<A>(0x6000e050, 0, 2);
        A::delay(2);
        wait_ready::<A>();
        modify::<A>(0x60006040, 1 << 18, 0);
    }
}

#[cfg(esp32c3)]
#[inline(always)]
pub(crate) unsafe fn pkdet<A: Access>() {
    unsafe {
        modify::<A>(0x6000e05c, 0, 1 << 21);
        modify::<A>(0x6000e05c, 0, 1 << 19);
        wait_ready::<A>();
        modify::<A>(0x6000e050, 2, 0);
        modify::<A>(0x6000e050, 0, 2);
        A::delay(10);
        wait_ready::<A>();
        modify::<A>(0x6000e05c, 1 << 21, 0);
        modify::<A>(0x6000e05c, 1 << 19, 0);
    }
}

#[inline(always)]
pub(crate) unsafe fn read_code<A: Access>() -> u32 {
    unsafe {
        let mut buffer = Samples(MaybeUninit::uninit());
        A::setup(function::<A>(SETUP));
        A::fill(function::<A>(OUTPUT), &mut buffer.0);
        buffer.0.as_ptr().cast::<u16>().add(1).read_volatile() as u32
    }
}

#[inline(always)]
pub(crate) unsafe fn samples<A: Access>(count: u32) -> u32 {
    #[cfg(esp32s3)]
    let count = count as u8 as u32;
    let mut counter = 0u8;
    let mut sum = 0u32;
    let mut buffer = Samples(MaybeUninit::uninit());
    unsafe {
        while u32::from(counter) != count {
            A::tone();
            A::fill(function::<A>(OUTPUT), &mut buffer.0);
            sum = sum.wrapping_add(buffer.0.as_ptr().cast::<u16>().add(1).read_volatile() as u32);
            counter = counter.wrapping_add(1);
        }
        // Preserve native divide-by-zero behavior and the 8-bit counter.
        A::divide_unsigned(sum, counter as u32) as u16 as u32
    }
}

#[inline(always)]
pub(crate) unsafe fn fm<A: Access>(signal: usize, reference: usize) -> u32 {
    unsafe { A::reference(A::samples(2), signal, reference) };
    0
}

#[inline(always)]
pub(crate) unsafe fn linear<A: Access>() -> i32 {
    let mut result = 0i16;
    for _ in 0..2 {
        let mut pair = MaybeUninit::<[u16; 2]>::uninit();
        let ptr = pair.as_mut_ptr().cast::<u16>();
        unsafe {
            A::reference(A::samples(2), ptr as usize, ptr.add(1) as usize);
            let denominator = A::read16(ptr.add(1) as usize) as i16;
            if denominator == 0 {
                A::write16(ptr.add(1) as usize, 1);
            }
            let numerator = (A::read16(ptr as usize) as i16 as i32) << 10;
            let denominator = A::read16(ptr.add(1) as usize) as i16 as i32;
            result = (i32::from(result) + numerator / denominator) as i16;
        }
    }
    result as i32
}

#[inline(always)]
pub(crate) unsafe fn db<A: Access>(offset: u32) -> i32 {
    #[cfg(esp32s3)]
    let offset = offset as u16 as u32;
    let mut pair = MaybeUninit::<[u16; 2]>::uninit();
    let ptr = pair.as_mut_ptr().cast::<u16>();
    unsafe {
        A::fm(ptr as usize, ptr.add(1) as usize);
        let first = A::convert(
            function::<A>(CONVERT),
            A::read16(ptr as usize) as i16 as i32,
            3,
        );
        let second = A::convert(
            function::<A>(CONVERT),
            A::read16(ptr.add(1) as usize) as i16 as i32,
            3,
        );
        offset.wrapping_add(first).wrapping_sub(second) as i16 as i32
    }
}

#[cfg(not(test))]
mod native {
    use super::{Access, MaybeUninit};
    unsafe extern "C" {
        static mut g_phyFuns: *const u8;
        static mut phy_param: u8;
        fn ets_delay_us(microseconds: u32);
    }
    pub(super) struct Native;
    impl Access for Native {
        #[inline(always)]
        unsafe fn param() -> usize {
            (&raw const phy_param) as usize
        }
        #[inline(always)]
        unsafe fn read16(address: usize) -> u16 {
            unsafe { (address as *const u16).read_volatile() }
        }
        #[inline(always)]
        unsafe fn write16(address: usize, value: u16) {
            unsafe { (address as *mut u16).write_volatile(value) }
        }
        #[inline(always)]
        unsafe fn read32(address: usize) -> u32 {
            unsafe { (address as *const u32).read_volatile() }
        }
        #[inline(always)]
        unsafe fn write32(address: usize, value: u32) {
            unsafe { (address as *mut u32).write_volatile(value) }
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
        unsafe fn setup(target: usize) {
            unsafe { core::mem::transmute::<usize, unsafe extern "C" fn()>(target)() }
        }
        #[inline(always)]
        unsafe fn fill(target: usize, output: &mut MaybeUninit<[u16; 8]>) {
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(*mut u16)>(target)(
                    output.as_mut_ptr().cast(),
                )
            }
        }
        #[inline(always)]
        unsafe fn convert(target: usize, value: i32, selector: u32) -> u32 {
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(i32, u32) -> u32>(target)(
                    value, selector,
                )
            }
        }
        #[inline(always)]
        unsafe fn delay(microseconds: u32) {
            unsafe { ets_delay_us(microseconds) }
        }
        #[inline(always)]
        unsafe fn tone() {
            unsafe { super::__opensensor_pwdet_tone() }
        }
        #[inline(always)]
        unsafe fn samples(count: u32) -> u32 {
            unsafe { super::__opensensor_pwdet_samples(count) }
        }
        #[inline(always)]
        unsafe fn reference(input: u32, signal: usize, reference: usize) {
            unsafe {
                super::__opensensor_pwdet_reference(
                    input,
                    signal as *mut u16,
                    reference as *mut u16,
                )
            }
        }
        #[inline(always)]
        unsafe fn fm(signal: usize, reference: usize) -> u32 {
            unsafe { super::__opensensor_pwdet_fm(signal as *mut u16, reference as *mut u16) }
        }
        #[inline(always)]
        unsafe fn divide_unsigned(numerator: u32, denominator: u32) -> u32 {
            #[cfg(esp32c3)]
            {
                if denominator == 0 {
                    u32::MAX
                } else {
                    numerator / denominator
                }
            }
            #[cfg(esp32s3)]
            {
                // QUOU raises the native integer-divide exception on zero.
                // Keep that behavior instead of introducing a Rust panic.
                let result;
                unsafe {
                    core::arch::asm!("quou {result}, {numerator}, {denominator}",
                    result = out(reg) result, numerator = in(reg) numerator,
                    denominator = in(reg) denominator, options(nomem, nostack));
                }
                result
            }
        }
    }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_pwdet_power() {
    power()
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
unsafe extern "C" fn __opensensor_pwdet_reference(
    input: u32,
    signal: *mut u16,
    reference: *mut u16,
) {
    unsafe { self::reference::<native::Native>(input, signal as usize, reference as usize) }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
unsafe extern "C" fn __opensensor_pwdet_tone() {
    unsafe { tone::<native::Native>() }
}
#[cfg(all(not(test), esp32c3))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_pwdet_pkdet() {
    unsafe { pkdet::<native::Native>() }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_pwdet_read() -> u32 {
    unsafe { read_code::<native::Native>() }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
unsafe extern "C" fn __opensensor_pwdet_samples(count: u32) -> u32 {
    unsafe { samples::<native::Native>(count) }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
unsafe extern "C" fn __opensensor_pwdet_fm(signal: *mut u16, reference: *mut u16) -> u32 {
    unsafe { fm::<native::Native>(signal as usize, reference as usize) }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_pwdet_linear() -> i32 {
    unsafe { linear::<native::Native>() }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_pwdet_db(offset: u32) -> i32 {
    unsafe { db::<native::Native>(offset) }
}
