//! Receive IQ tone orchestration and bounded convergence search.
//! Tone generation, IQ correction and the writable difference callback remain
//! explicit boundaries; argument widths follow each chip's pinned ABI.
#![allow(dead_code)]
pub(crate) trait Access {
    unsafe fn read(address: usize, width: usize) -> u32;
    unsafe fn write(address: usize, width: usize, value: u32);
    unsafe fn start(frequency: u32, gain: u32);
    unsafe fn stop();
    unsafe fn correct(mode: u32, magnitude: usize, phase: usize, logging: u32);
    unsafe fn log(index: u32, magnitude: i32, phase: i32);
    unsafe fn table_global() -> usize;
    unsafe fn difference(target: usize, value: i32) -> i32;
    unsafe fn local(kind: u32, pointer: *mut u8) -> usize;
    unsafe fn sample(mode: u32, frequency: u32, gain: u32, output: usize, logging: u32);
}
const S3: bool = cfg!(esp32s3);
#[inline(always)]
fn byte(v: u32) -> u32 {
    if S3 { v as u8 as u32 } else { v }
}
#[inline(always)]
fn frequency(v: u32) -> u32 {
    if S3 { v as i16 as i32 as u32 } else { v }
}
#[inline(always)]
pub(crate) unsafe fn sample<A: Access>(
    mode: u32,
    tone_frequency: u32,
    gain: u32,
    output: usize,
    logging: u32,
) {
    unsafe {
        let value = A::read(0x6000607c, 4);
        A::write(0x6000607c, 4, value | 0x08000000);
        let value = A::read(0x6000607c, 4);
        A::write(0x6000607c, 4, value & 0xefffffff);
        A::start(frequency(tone_frequency), byte(gain));
        let mut storage = core::mem::MaybeUninit::<[u8; 2]>::uninit();
        let buffer = A::local(1, storage.as_mut_ptr().cast());
        A::correct(byte(mode), buffer, buffer + 1, byte(logging));
        A::stop();
        let magnitude = A::read(buffer, 1);
        A::write(output, 1, magnitude);
        let phase = A::read(buffer + 1, 1);
        A::write(output + 1, 1, phase);
    }
}
#[inline(always)]
pub(crate) unsafe fn collect<A: Access>(tone_frequency: u32, gain: u32, logging: u32) -> u32 {
    unsafe {
        let tone_frequency = frequency(tone_frequency);
        let gain = byte(gain);
        let logging = byte(logging);
        let mut storage = core::mem::MaybeUninit::<[u8; 2]>::uninit();
        let buffer = A::local(0, storage.as_mut_ptr().cast());
        let (mut previous_m, mut previous_p) = (0i32, 0i32);
        let (mut sum_m, mut sum_p) = (0i16, 0i16);
        let (mut magnitude, mut phase) = (0i32, 0i32);
        for index in 0..4 {
            A::sample(14, tone_frequency, gain, buffer, logging);
            if logging != 0 {
                let p = A::read(buffer + 1, 1) as i8 as i32;
                let m = A::read(buffer, 1) as i8 as i32;
                A::log(index, m, p);
            }
            if index != 0 {
                let (table, m) = if S3 {
                    let m = A::read(buffer, 1) as i8 as i32;
                    (A::read(A::table_global(), 4) as usize, m)
                } else {
                    let table = A::read(A::table_global(), 4) as usize;
                    (table, A::read(buffer, 1) as i8 as i32)
                };
                let slot = if S3 { 0xec } else { 0x100 };
                let target = A::read(table + slot, 4) as usize;
                if A::difference(target, previous_m - m) <= 1 {
                    let table = A::read(A::table_global(), 4) as usize;
                    let p = A::read(buffer + 1, 1) as i8 as i32;
                    let target = A::read(table + slot, 4) as usize;
                    if A::difference(target, previous_p - p) <= 1 {
                        let m = A::read(buffer, 1) as i8 as i32;
                        let p = A::read(buffer + 1, 1) as i8 as i32;
                        magnitude = ((previous_m + m + 1) >> 1) as i8 as i32;
                        phase = ((previous_p + p + 1) >> 1) as i8 as i32;
                        break;
                    }
                }
            }
            previous_m = A::read(buffer, 1) as i8 as i32;
            previous_p = A::read(buffer + 1, 1) as i8 as i32;
            sum_m = sum_m.wrapping_add(previous_m as i16);
            sum_p = sum_p.wrapping_add(previous_p as i16);
            magnitude = ((sum_m as i32 + 2) >> 2) as i8 as i32;
            phase = ((sum_p as i32 + 2) >> 2) as i8 as i32;
        }
        ((magnitude.clamp(-31, 31) as u32 & 63) << 6) | (phase.clamp(-31, 31) as u32 & 63)
    }
}
include!("phy_rf_iq_native.rs");
