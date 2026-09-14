//! S3 spur configuration and power estimation, preserving the vendor ABI.
//!
//! The access boundary keeps callback dispatch, MMIO widths and QUOS trapping
//! explicit; its physical effects must be checked in emitted/device profiles.
pub trait Access {
    unsafe fn read(address: usize, width: usize) -> u32;
    unsafe fn write(address: usize, width: usize, value: u32);
    unsafe fn parameter() -> usize;
    unsafe fn table_global() -> usize;
    unsafe fn call(target: usize, kind: u32, args: &[u32]) -> u32;
    unsafe fn quotient(numerator: i32, denominator: i32) -> i32;
}

#[inline(always)]
unsafe fn call<A: Access>(kind: u32, args: &[u32]) -> u32 {
    unsafe {
        let target = if kind < 7 {
            const OFFSETS: [usize; 7] = [0x1d4, 0x50, 0x4c, 0x40, 0xf0, 0xf4, 0x104];
            let table = A::read(A::table_global(), 4) as usize;
            A::read(table + OFFSETS[kind as usize], 4) as usize
        } else {
            0
        };
        A::call(target, kind, args)
    }
}

#[inline(always)]
fn scale(value: u32) -> u32 {
    // Multiplication is intentionally wrapped before signed division by 100.
    ((value.wrapping_shl(10) as i32) / 100) as u32
}

#[inline(always)]
unsafe fn clear<A: Access>(address: usize) {
    unsafe {
        let current = A::read(address, 4);
        A::write(address, 4, current & !0x2000);
    }
}

#[inline(always)]
pub unsafe fn configure<A: Access>(arguments: [u32; 7]) {
    unsafe {
        let channel = arguments[0] as i8 as i32;
        let mode = arguments[1] as i8;
        let forced = arguments[2] as u8;
        let width = arguments[3] as u8;
        let flags = arguments[4] as u16 as u32;
        let coefficient = arguments[5] as u16 as u32;
        let enabled = arguments[6] as u8 as u32;
        let multiplier = if mode < 2 { 10 } else { 20 };
        let divisor = call::<A>(0, &[channel as u32]);
        let width_value = match width {
            1 => 26,
            2 => 24,
            _ => 40,
        };
        let param = A::parameter();
        if forced != 0 || (A::read(param + 0x2a6, 1) != 0 && A::read(param + 0x2d7, 1) > 10) {
            let actual_width = if A::read(param + 0x2a6, 1) != 0 {
                48
            } else {
                width_value
            };
            let value = call::<A>(1, &[divisor, multiplier, actual_width, 1]);
            call::<A>(2, &[0, scale(value)]);
        } else {
            clear::<A>(0x6001d014);
        }
        if flags != 0 {
            let value = call::<A>(1, &[divisor, multiplier, coefficient, enabled]);
            let shift = channel.wrapping_sub(1) as u32;
            let active = value != 0 && (flags >> 14) & flags.wrapping_shr(shift) & 1 != 0;
            call::<A>(2, &[1, if active { scale(value) } else { 0 }]);
        } else {
            clear::<A>(0x6001d018);
        }
        let shift = (A::read(0x6001cc48, 4) >> 24) & 31;
        let numerator = 80u32.wrapping_shl(shift) as i32;
        let second = A::read(0x6001cc48, 4);
        // On Xtensa the access adapter must issue QUOS: zero faults and the
        // signed minimum/-1 result wraps, unlike ordinary Rust division.
        let quotient = A::quotient(numerator, divisor as i32) as u32;
        A::write(0x6001cc48, 4, (second & 0xff000000) | (quotient & 0xffffff));
    }
}

#[inline(always)]
pub unsafe fn power<A: Access>(logging: u32) {
    unsafe {
        let timer = A::read(0x60035000, 4);
        call::<A>(7, &[7, 0]);
        call::<A>(8, &[2443, 0]);
        call::<A>(3, &[1, 54]);
        call::<A>(9, &[1, 128, 0, 0, 0, 0]);
        let mut associated = 0u32;
        let mut minimum = 0u32;
        let mut iteration = 0u32;
        loop {
            call::<A>(4, &[1, 4095]);
            let a = A::read(0x60006148, 4);
            let b = A::read(0x6000614c, 4);
            let c = A::read(0x60006150, 4);
            let d = A::read(0x60006154, 4);
            let x = a.wrapping_add(d) as i32 as i64;
            let y = b.wrapping_sub(c) as i32 as i64;
            let sum = (x * x) as u64 + (y * y) as u64;
            let high = ((sum >> 32) as i32) >> 6;
            let first = call::<A>(6, &[high as u32, 0]);
            let word = (A::read(0x60006164, 4) as i32) >> 9;
            let second = call::<A>(6, &[word as u32, 0]);
            let candidate = ((second.wrapping_add(8) as i32) >> 4) as u32;
            call::<A>(5, &[]);
            if iteration == 0 || candidate < minimum {
                associated = ((first.wrapping_add(8) as i32) >> 4) as u32;
                minimum = candidate;
            }
            if minimum <= 24 {
                break;
            }
            iteration += 1;
            if iteration == 10 {
                break;
            }
        }
        call::<A>(9, &[0, 128, 0, 0, 0, 0]);
        call::<A>(3, &[0, 54]);
        let param = A::parameter();
        A::write(param + 0x2d7, 1, associated);
        A::write(param + 0x2d8, 1, minimum);
        if logging as u8 != 0 {
            let elapsed = A::read(0x60035000, 4).wrapping_sub(timer);
            call::<A>(10, &[0, iteration, elapsed, associated, minimum]);
        }
    }
}

#[cfg(all(not(test), target_arch = "xtensa"))]
include!("phy_spur_native.rs");
