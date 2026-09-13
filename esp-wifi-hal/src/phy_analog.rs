//! RC measurement sequencing and calibration arithmetic. Analog access and
//! soft-double operations retain their existing ROM boundaries.

pub(crate) trait Access {
    unsafe fn param() -> usize;
    #[cfg(esp32c3)]
    unsafe fn divisors() -> [usize; 2];
    unsafe fn read8(address: usize) -> u8;
    #[cfg(esp32c3)]
    unsafe fn read16(address: usize) -> u16;
    unsafe fn read32(address: usize) -> u32;
    unsafe fn write8(address: usize, value: u8);
    unsafe fn write32(address: usize, value: u32);
    unsafe fn table() -> usize;
    unsafe fn slot(table: usize, offset: usize) -> usize;
    unsafe fn masked_write(target: usize, args: [u32; 6]);
    unsafe fn masked_read(target: usize, args: [u32; 5]) -> u32;
    unsafe fn delay(microseconds: u32);
    unsafe fn measurement(selector: u32) -> u32;
    unsafe fn soft_double(operation: u32, left: u64, right: u64) -> u64;
}

const WRITE: usize = if cfg!(esp32c3) { 0x1bc } else { 0x198 };
const READ: usize = WRITE - 4;

#[inline(always)]
unsafe fn function<A: Access>(slot: usize) -> usize {
    unsafe { A::slot(A::table(), slot) }
}

#[inline(always)]
pub(crate) unsafe fn measurement<A: Access>(selector: u32) -> u32 {
    unsafe {
        A::masked_write(function::<A>(WRITE), [106, 0, 2, 6, 5, 2]);
        A::masked_write(function::<A>(WRITE), [106, 0, 6, 4, 0, 2]);
        let setting = match selector as u8 {
            1 => 7,
            2 => 6,
            #[cfg(esp32c3)]
            3 => 13,
            _ => 11,
        };
        A::masked_write(function::<A>(WRITE), [106, 0, 4, 7, 4, setting]);
        A::masked_write(function::<A>(WRITE), [97, 0, 8, 2, 2, 1]);
        A::masked_write(function::<A>(WRITE), [106, 0, 4, 0, 0, 1]);
        A::masked_write(function::<A>(WRITE), [106, 0, 4, 3, 3, 0]);
        A::masked_write(function::<A>(WRITE), [106, 0, 4, 3, 3, 1]);
        A::delay(100);
        let result = A::masked_read(function::<A>(READ), [106, 0, 5, 5, 0]);
        A::masked_write(function::<A>(WRITE), [97, 0, 8, 2, 2, 0]);
        A::masked_write(function::<A>(WRITE), [106, 0, 4, 0, 0, 0]);
        result
    }
}

#[inline(always)]
fn divided(numerator: i32, denominator: u16) -> i16 {
    // C3's mutable divisors may be zero. Its signed DIV returns all ones.
    let value = if denominator == 0 {
        -1
    } else {
        numerator / i32::from(denominator)
    };
    value.wrapping_sub(8) as i16
}

#[inline(always)]
unsafe fn double_code<A: Access>(numerator: u64, divisor: f64) -> i16 {
    unsafe {
        let ratio = A::soft_double(1, numerator, divisor.to_bits());
        let adjusted = A::soft_double(2, ratio, 8.0f64.to_bits());
        A::soft_double(3, adjusted, 0) as i16
    }
}

#[inline(always)]
unsafe fn write_codes<A: Access>(address: usize, values: [i16; 4]) {
    for (index, value) in values.into_iter().enumerate() {
        unsafe { A::write8(address + index, value.clamp(2, 63) as u8) };
    }
}

#[inline(always)]
pub(crate) unsafe fn calibrate<A: Access>() {
    unsafe {
        let param = A::param();
        if A::read32(param + 0x120) & (1 << 23) != 0 {
            return;
        }
        let mode = A::read8(param + if cfg!(esp32c3) { 0x322 } else { 0x2a5 });
        let (ht20, ht40) = if mode == 0 {
            (190, 410)
        } else {
            #[cfg(esp32c3)]
            {
                let [left, right] = A::divisors();
                (A::read16(left), A::read16(right))
            }
            #[cfg(esp32s3)]
            {
                (155, 355)
            }
        };
        let selector = A::read8(param + 0xf3);
        let sample = A::measurement(selector.into());
        A::write8(param + 0x166, sample as u8);
        let numerator = sample.wrapping_add(56).wrapping_mul(82) as i32;
        write_codes::<A>(
            param + 0x167,
            [
                divided(numerator, 190),
                divided(numerator, ht20),
                divided(numerator, 410),
                divided(numerator, ht40),
            ],
        );
        // Preserve each ROM call, including the original raw double return
        // reused across the two division/subtraction/conversion sequences.
        let double = A::soft_double(0, numerator as u32 as u64, 0);
        let first = double_code::<A>(double, 260.0);
        let common = divided(numerator, 312);
        let second = double_code::<A>(double, if cfg!(esp32c3) { 156.0 } else { 197.6 });
        write_codes::<A>(param + 0x16b, [first, common, second, common]);
        let flags = A::read32(param + 0x120);
        A::write32(param + 0x120, flags | (1 << 23));
    }
}

#[cfg(all(not(test), esp32c3))]
#[unsafe(no_mangle)]
static mut __opensensor_analog_ht20: u16 = 155;
#[cfg(all(not(test), esp32c3))]
#[unsafe(no_mangle)]
static mut __opensensor_analog_ht40: u16 = 355;

#[cfg(not(test))]
mod native {
    use super::Access;
    unsafe extern "C" {
        static mut phy_param: u8;
        static mut g_phyFuns: *const u8;
        fn ets_delay_us(microseconds: u32);
        fn __floatsidf(value: i32) -> f64;
        fn __divdf3(left: f64, right: f64) -> f64;
        fn __subdf3(left: f64, right: f64) -> f64;
        fn __fixdfsi(value: f64) -> i32;
    }
    pub(super) struct Native;
    impl Access for Native {
        #[inline(always)]
        unsafe fn param() -> usize {
            (&raw const phy_param) as usize
        }
        #[cfg(esp32c3)]
        #[inline(always)]
        unsafe fn divisors() -> [usize; 2] {
            [
                (&raw const super::__opensensor_analog_ht20) as usize,
                (&raw const super::__opensensor_analog_ht40) as usize,
            ]
        }
        #[inline(always)]
        unsafe fn read8(address: usize) -> u8 {
            unsafe { (address as *const u8).read_volatile() }
        }
        #[cfg(esp32c3)]
        #[inline(always)]
        unsafe fn read16(address: usize) -> u16 {
            unsafe { (address as *const u16).read_volatile() }
        }
        #[inline(always)]
        unsafe fn read32(address: usize) -> u32 {
            unsafe { (address as *const u32).read_volatile() }
        }
        #[inline(always)]
        unsafe fn write8(address: usize, value: u8) {
            unsafe { (address as *mut u8).write_volatile(value) }
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
        unsafe fn masked_write(target: usize, a: [u32; 6]) {
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32, u32, u32, u32, u32)>(
                    target,
                )(a[0], a[1], a[2], a[3], a[4], a[5])
            }
        }
        #[inline(always)]
        unsafe fn masked_read(target: usize, a: [u32; 5]) -> u32 {
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32, u32, u32, u32) -> u32>(
                    target,
                )(a[0], a[1], a[2], a[3], a[4])
            }
        }
        #[inline(always)]
        unsafe fn delay(microseconds: u32) {
            unsafe { ets_delay_us(microseconds) }
        }
        #[inline(always)]
        unsafe fn measurement(selector: u32) -> u32 {
            unsafe { super::__opensensor_analog_measurement(selector) }
        }
        #[inline(always)]
        unsafe fn soft_double(operation: u32, left: u64, right: u64) -> u64 {
            unsafe {
                match operation {
                    0 => __floatsidf(left as u32 as i32).to_bits(),
                    1 => __divdf3(f64::from_bits(left), f64::from_bits(right)).to_bits(),
                    2 => __subdf3(f64::from_bits(left), f64::from_bits(right)).to_bits(),
                    3 => __fixdfsi(f64::from_bits(left)) as u32 as u64,
                    _ => unreachable!(),
                }
            }
        }
    }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
unsafe extern "C" fn __opensensor_analog_measurement(selector: u32) -> u32 {
    unsafe { measurement::<native::Native>(selector) }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_analog_calibrate() {
    unsafe { calibrate::<native::Native>() }
}
