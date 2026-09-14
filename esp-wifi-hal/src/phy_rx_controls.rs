//! Receive saturation and IQ-estimator controls for the pinned C3/S3 PHY ABI.
//!
//! The estimator's hardware-completion loop and 16-bit saturation counter are
//! preserved. Calibration searches and ROM callbacks remain external boundaries.
#![allow(dead_code)]

pub(crate) trait Access {
    unsafe fn parameter() -> usize;
    unsafe fn table_global() -> usize;
    unsafe fn read(address: usize, width: usize) -> u32;
    unsafe fn write(address: usize, width: usize, value: u32);
    unsafe fn delay(microseconds: u32);
    unsafe fn callback(target: usize, argument: Option<usize>);
    unsafe fn local(pointer: *mut u16) -> usize;
    unsafe fn trigger();
}
const S3: bool = cfg!(esp32s3);
pub(crate) const COUNT: usize = if S3 { 736 } else { 842 };
pub(crate) const SATURATED: usize = if S3 { 730 } else { 844 };

#[inline(always)]
pub(crate) unsafe fn reset<A: Access>(enabled: u32) {
    unsafe {
        let enabled = if S3 { enabled as u8 as u32 } else { enabled };
        A::write(0x6001c068, 4, 0x404);
        let v = A::read(0x6001c05c, 4);
        A::write(
            0x6001c05c,
            4,
            if enabled != 0 {
                v | 0xd1080000
            } else {
                v & 0x2ef7ffff
            },
        );
        let v = A::read(0x6001c05c, 4);
        A::write(
            0x6001c05c,
            4,
            (v & 0xfff80000) | if enabled != 0 { 0x800 } else { 0x400 },
        );
    }
}

#[inline(always)]
pub(crate) unsafe fn trigger<A: Access>() {
    unsafe {
        let v = A::read(0x6001c02c, 4);
        A::write(0x6001c02c, 4, (v & 0x00ffffff) | 0x46000000);
        let v = A::read(0x6001c02c, 4);
        A::write(0x6001c02c, 4, v | 0x00800000);
        A::delay(1);
        let v = A::read(0x6001c02c, 4);
        A::write(0x6001c02c, 4, v & 0xff7fffff);
    }
}

#[inline(always)]
pub(crate) unsafe fn estimate<A: Access>(_mode: u32, samples: u32) {
    unsafe {
        let p = A::parameter();
        let v = A::read(0x60006140, 4);
        A::write(p + COUNT, 2, 0);
        A::write(0x60006140, 4, (v & 0xf3ffffff) | 0x04000000);
        let v = A::read(0x60006144, 4);
        A::write(0x60006144, 4, (v & 0xffe7ffff) | 0x00100000);
        let v = A::read(0x60006144, 4);
        A::write(0x60006144, 4, (v & 0xfffe0003) | ((samples << 2) & 0x1fffc));
        let v = A::read(0x60006144, 4);
        A::write(0x60006144, 4, v | 1);
        A::delay(1);
        let v = A::read(0x60006144, 4);
        A::write(0x60006144, 4, v | 2);
        A::trigger();
        let mut count = A::read(p + COUNT, 2) as u16;
        let mut changed = false;
        while A::read(0x60006174, 4) & 0x10000 == 0 {
            if (A::read(0x6001c08c, 4) >> 12) & 127 <= 69 {
                count = count.wrapping_add(1);
                changed = true;
            }
        }
        if changed {
            A::write(p + COUNT, 2, count as u32);
        }
    }
}

#[inline(always)]
unsafe fn callback<A: Access>(offset: usize, argument: Option<usize>) {
    unsafe {
        let table = A::read(A::table_global(), 4) as usize;
        let target = A::read(table + offset, 4) as usize;
        A::callback(target, argument);
    }
}

#[inline(always)]
pub(crate) unsafe fn check<A: Access>() {
    unsafe {
        let mut storage = core::mem::MaybeUninit::<[u16; 4]>::uninit();
        let buffer = A::local(storage.as_mut_ptr().cast());
        // Original readonly input is four little-endian halfwords, each 0x100.
        for i in 0..4 {
            A::write(buffer + i * 2, 2, 0x100);
        }
        callback::<A>(if S3 { 0x1b0 } else { 0x1d4 }, None);
        callback::<A>(if S3 { 0x1c0 } else { 0x1e4 }, Some(0));
        callback::<A>(if S3 { 0x1cc } else { 0x1f0 }, Some(buffer));
        A::trigger();
        A::delay(5);
        let mut count = 0u16;
        for _ in 0..100 {
            if (A::read(0x6001c08c, 4) >> 12) & 127 <= 69 {
                count += 1;
            }
        }
        if count != 0 {
            A::write(A::parameter() + SATURATED, 1, 1);
        }
        callback::<A>(if S3 { 0x1b4 } else { 0x1d8 }, None);
    }
}

include!("phy_rx_controls_native.rs");
