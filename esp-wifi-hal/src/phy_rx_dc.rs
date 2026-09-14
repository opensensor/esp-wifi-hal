//! Receive DC estimate selection and in-place channel table filling.
//! Analog estimation and distance callbacks remain external boundaries.
#![allow(dead_code)]
pub(crate) trait Access {
    unsafe fn read(address: usize, width: usize) -> u32;
    unsafe fn write(address: usize, width: usize, value: u32);
    unsafe fn table_global() -> usize;
    unsafe fn parameter_address() -> usize;
    unsafe fn local(pointer: *mut u32) -> usize;
    unsafe fn estimate(target: usize, samples: u32, output: usize);
    unsafe fn difference(target: usize, value: i32) -> i32;
}
const S3: bool = cfg!(esp32s3);

#[inline(always)]
pub(crate) unsafe fn minimum<A: Access>(samples: u32, _unused: u32, output: usize) {
    unsafe {
        let samples = if S3 { samples as u16 as u32 } else { samples };
        let mut storage = core::mem::MaybeUninit::<[u32; 3]>::uninit();
        let buffer = A::local(storage.as_mut_ptr().cast());
        let parameter = A::parameter_address();
        let (gate, selector) = if S3 { (736, 730) } else { (842, 844) };
        let mut best = 100i32;
        for attempt in 0..8 {
            let table = A::read(A::table_global(), 4) as usize;
            let target = A::read(table + if S3 { 0xf8 } else { 0x10c }, 4) as usize;
            A::estimate(target, samples, buffer);
            let score = A::read(buffer + 8, 4) as i32;
            if score < best
                && (A::read(parameter + gate, 2) == 0 || A::read(parameter + selector, 1) == 1)
            {
                let first = A::read(buffer, 4);
                A::write(output + 8, 4, score as u32);
                best = score;
                A::write(output, 4, first);
                let second = A::read(buffer + 4, 4);
                A::write(output + 4, 4, second);
            }
            if best <= 35 || (best <= 47 && attempt >= 2) {
                return;
            }
        }
        A::write(output + 8, 4, 56);
        A::write(output, 4, 0);
        A::write(output + 4, 4, 0);
    }
}

#[inline(always)]
pub(crate) unsafe fn sort<A: Access>(data: usize, status: usize) {
    unsafe {
        let columns = if S3 { 1 } else { 3 };
        // C3 carries the previous column's preference into this count. Only
        // column zero can fall back to status 2; resetting each column changes
        // the original routine's behavior when later columns lack status 1.
        let mut preference = 0u8;
        for column in 0..columns {
            for channel in 0..14 {
                if A::read(status + channel * columns + column, 1) == 1 {
                    preference = preference.wrapping_add(1);
                }
            }
            preference = if preference == 0 { 2 } else { 1 };
            for channel in 0..14 {
                if A::read(status + channel * columns + column, 1) == 1 {
                    continue;
                }
                let (mut selected, mut distance) = (channel, 20i8);
                for candidate in 0..14 {
                    if A::read(status + candidate * columns + column, 1) != preference as u32 {
                        continue;
                    }
                    let table = A::read(A::table_global(), 4) as usize;
                    let target = A::read(table + if S3 { 0xec } else { 0x100 }, 4) as usize;
                    let value = A::difference(target, channel as i32 - candidate as i32) as i8;
                    if value < distance {
                        selected = candidate;
                        distance = value;
                    }
                }
                let value = A::read(data + (selected * columns + column) * 4, 4);
                A::write(
                    data + (channel * columns + column) * 4,
                    4,
                    value & 0xffff01ff,
                );
            }
        }
    }
}
include!("phy_rx_dc_native.rs");
