//! Integer IQ mismatch conversion and two-round receive correction.
//! Analog estimation, register programming and signed-wide ROM division remain
//! explicit boundaries. Intermediate widths follow the pinned C3/S3 routines.
#![allow(dead_code)]
pub(crate) trait Access {
    unsafe fn read(address: usize, width: usize) -> u32;
    unsafe fn write(address: usize, width: usize, value: u32);
    unsafe fn divide(numerator: i64, denominator: i64) -> i64;
    unsafe fn log(sample: i32, magnitude: i32, phase: i32);
    unsafe fn set(coefficient: i32, mode: u32) -> u32;
    unsafe fn table_global() -> usize;
    unsafe fn callback(target: usize, samples: Option<u32>);
    unsafe fn local(pointer: *mut u8) -> usize;
    unsafe fn measure(mode: u32, output: usize, logging: u32);
}
const S3: bool = cfg!(esp32s3);
#[inline(always)]
fn byte_arg(v: u32) -> u32 {
    if S3 { v as u8 as u32 } else { v }
}
#[inline(always)]
pub(crate) unsafe fn mismatch<A: Access>(mode: u32, output: usize, logging: u32) {
    unsafe {
        let mode = byte_arg(mode);
        let shift = mode.wrapping_sub(2) & 31;
        let a = (A::read(0x60006148, 4) as i32) >> shift;
        let d = (A::read(0x60006154, 4) as i32) >> shift;
        let c = (A::read(0x60006150, 4) as i32) >> shift;
        let b = (A::read(0x6000614c, 4) as i32) >> shift;
        let x = a.wrapping_add(d) as i64;
        let y = b.wrapping_sub(c) as i64;
        let u = a.wrapping_sub(d) as i64;
        let v = c.wrapping_add(b) as i64;
        let denominator = (x * x).wrapping_add(y * y);
        let denominator = if denominator == 0 { 1 } else { denominator };
        let first = (x * u).wrapping_sub(y * v).wrapping_shl(9);
        let second = (x * v).wrapping_add(y * u).wrapping_shl(9);
        let magnitude = ((A::divide(first, denominator) as i8 as i32) + 1) >> 1;
        let phase = ((A::divide(second, denominator) as i8 as i32) + 1) >> 1;
        A::write(output, 1, magnitude as u32);
        A::write(output + 1, 1, phase as u32);
        if byte_arg(logging) != 0 {
            let sample = (A::read(0x60006164, 4) as i32) >> (mode.wrapping_sub(3) & 31);
            A::log(sample, magnitude, phase);
        }
    }
}
#[inline(always)]
pub(crate) unsafe fn correct<A: Access>(
    mode: u32,
    magnitude_output: usize,
    phase_output: usize,
    logging: u32,
) {
    unsafe {
        let mode = byte_arg(mode);
        let logging = byte_arg(logging);
        let samples = 1u32.wrapping_shl(mode) as u16 as u32;
        let mut storage = core::mem::MaybeUninit::<[u8; 2]>::uninit();
        let buffer = A::local(storage.as_mut_ptr().cast());
        let mut magnitude = 0u32;
        let mut phase = 0u32;
        for _ in 0..2 {
            let signed_phase = phase as i8 as i32;
            let correction = ((signed_phase * signed_phase + 128) >> 8) as u8 as u32;
            magnitude = byte_arg(A::set(magnitude.wrapping_sub(correction) as i8 as i32, 1));
            phase = byte_arg(A::set(signed_phase, 0));
            let table = A::read(A::table_global(), 4) as usize;
            let target = A::read(table + if S3 { 0xf0 } else { 0x104 }, 4) as usize;
            A::callback(target, Some(samples));
            A::measure(mode, buffer, logging);
            let (m, p) = if S3 {
                let m = A::read(buffer, 1);
                let p = A::read(buffer + 1, 1);
                (m, p)
            } else {
                let p = A::read(buffer + 1, 1);
                let m = A::read(buffer, 1);
                (m, p)
            };
            magnitude = magnitude.wrapping_add(correction).wrapping_add(m);
            phase = phase.wrapping_sub(p);
            let table = A::read(A::table_global(), 4) as usize;
            let target = A::read(table + if S3 { 0xf4 } else { 0x108 }, 4) as usize;
            A::callback(target, None);
            magnitude = magnitude as u8 as u32;
            phase = phase as u8 as u32;
        }
        let magnitude = (magnitude as i8 as i32).clamp(-31, 31);
        let phase = (phase as i8 as i32).clamp(-31, 31);
        A::set(magnitude, 1);
        A::set(phase, 0);
        A::write(magnitude_output, 1, magnitude as u32);
        A::write(phase_output, 1, phase as u32);
    }
}
include!("phy_rx_iq_native.rs");
