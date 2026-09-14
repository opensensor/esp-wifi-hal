//! Receive gain IQ/DC calibration, preserving the private PHY caller ABI.
//!
//! Callers provide valid aligned buffers and the bounded stage/count domain
//! documented in PHY-RX-GAIN-CAL.md. All externally visible memory is volatile.
const S3: bool = cfg!(esp32s3);
pub(crate) trait Access {
    unsafe fn read(a: usize, width: usize) -> u32;
    unsafe fn write(a: usize, width: usize, value: u32);
    unsafe fn parameter() -> usize;
    unsafe fn table_global() -> usize;
    unsafe fn local(pointer: *mut u8, kind: u32, size: usize) -> usize;
    unsafe fn call(target: usize, kind: u32, args: &[usize]) -> u32;
}
#[inline(always)]
fn byte(value: u32) -> u32 {
    if S3 { value as u8 as u32 } else { value }
}
#[inline(always)]
unsafe fn target<A: Access>(kind: u32) -> usize {
    let offsets = if S3 {
        [404, 408, 36, 72, 68, 28, 424, 428, 240, 244, 440]
    } else {
        [440, 444, 36, 84, 80, 28, 460, 464, 260, 264, 476]
    };
    unsafe {
        A::read(
            A::read(A::table_global(), 4) as usize + offsets[kind as usize],
            4,
        ) as usize
    }
}
#[inline(always)]
unsafe fn call<A: Access>(kind: u32, args: &[usize]) -> u32 {
    unsafe {
        let t = if kind < 11 { target::<A>(kind) } else { 0 };
        A::call(t, kind, args)
    }
}
#[inline(always)]
unsafe fn i2c<A: Access>(value: Option<u32>) -> u32 {
    unsafe {
        if let Some(v) = value {
            call::<A>(1, &[103, if S3 { 0 } else { 1 }, 3, 2, 2, v as usize])
        } else {
            call::<A>(0, &[103, if S3 { 0 } else { 1 }, 3, 2, 2])
        }
    }
}
#[inline(always)]
unsafe fn update<A: Access>(mask: u32, value: u32) {
    unsafe {
        let old = A::read(0x6000607c, 4);
        A::write(0x6000607c, 4, (old & mask) | value);
    }
}
#[inline(always)]
pub(crate) unsafe fn iq<A: Access>(policy: u32, frequency: u32, output: usize, logging: u32) {
    unsafe {
        let policy = byte(policy);
        let logging = byte(logging);
        let frequency = if S3 {
            frequency as i16 as i32 as u32
        } else {
            frequency
        };
        let mut storage = core::mem::MaybeUninit::<[u32; 2]>::uninit();
        let coefficients = A::local(storage.as_mut_ptr().cast(), 0, 8);
        let saved = if policy != 0 {
            let v = i2c::<A>(None);
            i2c::<A>(Some(0));
            v
        } else {
            0
        };
        call::<A>(2, &[1]);
        call::<A>(3, &[1]);
        call::<A>(4, &[1]);
        update::<A>(u32::MAX, 0x08000000);
        update::<A>(0xefffffff, 0);
        update::<A>(0xffffefff, 0);
        let packed = A::read(A::parameter() + 0x14c, 2);
        let first = ((packed << 21) as i32) >> 27;
        let second = ((packed << 26) as i32) >> 26;
        call::<A>(22, &[first as u32 as usize, 1]);
        call::<A>(22, &[second as u32 as usize, 0]);
        A::write(coefficients, 2, 256);
        A::write(coefficients + 2, 2, 256);
        let gains = [63u8, 31, 15, 7, 3, 1, 0];
        for phase in 0..2usize {
            let mut coarse = phase + 2;
            let mut fine = 24i32;
            let mut selected = 0;
            for _ in 0..4 {
                // Four iterations starting at coarse 2/3 keep this index 0..6.
                selected = *gains.get_unchecked(coarse) as usize;
                call::<A>(5, &[selected, 260, 128 + phase * 32]);
                call::<A>(20, &[4000, coefficients, 10, 0, 0]);
                call::<A>(6, &[1, 1, 497]);
                call::<A>(6, &[1, 1, 505]);
                call::<A>(23, &[1, frequency as usize, fine as u8 as usize, 0, 0, 0]);
                call::<A>(8, &[1, 1023]);
                let power = (A::read(0x60006164, 4) as i32) >> 7;
                if logging != 0 {
                    let first = call::<A>(7, &[5, 1]);
                    let second = call::<A>(7, &[1, 2]);
                    let x = (A::read(0x6000615c, 4) as i32) >> 16;
                    let y = (A::read(0x60006160, 4) as i32) >> 16;
                    call::<A>(
                        29,
                        &[
                            0,
                            power as u32 as usize,
                            16384,
                            131072,
                            first as usize,
                            second as usize,
                            fine as u32 as usize,
                            x as u32 as usize,
                            y as u32 as usize,
                        ],
                    );
                }
                call::<A>(9, &[]);
                call::<A>(24, &[1]);
                if power > 131072 {
                    if coarse < 6 {
                        coarse += 1;
                    } else {
                        fine = (fine + 20) as i16 as i32;
                    }
                } else if power < 16384 {
                    if coarse > 0 {
                        coarse -= 1;
                    } else {
                        fine = (fine - 20) as i16 as i32;
                    }
                } else {
                    break;
                }
                // Exhaustive four-step range proof: unclamped fine stays -16..44.
                // Only the lower clamp can change a value.
                fine = fine.max(0);
            }
            if logging != 0 {
                call::<A>(
                    29,
                    &[
                        1,
                        selected,
                        260,
                        fine as u32 as usize,
                        128 + phase * 32,
                        phase,
                        2,
                    ],
                );
            }
            let result = call::<A>(
                25,
                &[frequency as usize, fine as u8 as usize, logging as usize],
            );
            A::write(output + phase * 2, 2, result);
        }
        if policy != 0 {
            i2c::<A>(Some(saved));
        }
        call::<A>(2, &[0]);
        update::<A>(u32::MAX, 0x10000000);
        update::<A>(u32::MAX, 4096);
    }
}
#[inline(always)]
pub(crate) unsafe fn dc<A: Access>(a: &[usize; 10]) {
    unsafe {
        let policy = byte(a[0] as u32);
        let mut mode = byte(a[1] as u32);
        let end = byte(a[2] as u32);
        let (codes, iq, dc, channels) = (a[3], a[4], a[5], a[6]);
        let count = byte(a[7] as u32);
        let middle = if S3 { a[8] as u8 as u32 } else { 4 };
        let mut coefficient_storage = core::mem::MaybeUninit::<[u16; 2]>::uninit();
        let mut output_storage = core::mem::MaybeUninit::<[u32; 3]>::uninit();
        let mut status_storage = core::mem::MaybeUninit::<[u8; 42]>::uninit();
        let coefficients = A::local(coefficient_storage.as_mut_ptr().cast(), 0, 4);
        let output = A::local(output_storage.as_mut_ptr().cast(), 1, 12);
        let status_base = A::local(
            status_storage.as_mut_ptr().cast(),
            2,
            if S3 { 14 } else { 42 },
        );
        call::<A>(3, &[1]);
        call::<A>(4, &[1]);
        call::<A>(26, &[14]);
        if !S3 {
            A::write(A::parameter() + 0x1f2, 1, 14);
        }
        let saved = if policy != 0 {
            let v = i2c::<A>(None);
            i2c::<A>(Some(0));
            v
        } else {
            0
        };
        let table = [0u16, 1, 5, 13, 29];
        while mode < end {
            let iterations = if mode == 2 { 7 } else { 1 };
            let columns = if mode == 0 {
                count
            } else if mode == 1 {
                middle
            } else if S3 {
                1
            } else {
                3
            };
            if mode == 0 || mode == 1 {
                A::write(coefficients, 2, 256);
                A::write(coefficients + 2, 2, 256);
            }
            let mut iq_index = if policy != 0 { 0 } else { 9 };
            let mut dc_index = 0u32;
            let mut channel_index = 0u32;
            for channel in 0..iterations {
                if mode == 2 {
                    call::<A>(26, &[2 * (channel + 1) as usize]);
                    if policy != 0 {
                        i2c::<A>(Some(0));
                    }
                }
                for col in 0..columns {
                    let gain = if mode == 0 {
                        A::read(codes + col as usize, 1) << 8
                    } else if mode == 1 {
                        ((*table.get_unchecked(col as usize) as u32 * 8)
                            | (A::read(codes + 2, 1) << 8))
                            & 65535
                    } else {
                        A::read(
                            codes + (if S3 { count - 1 } else { count + col - 3 }) as usize,
                            1,
                        ) << 8
                    };
                    call::<A>(10, &[gain as usize]);
                    if mode == 1 {
                        let t = target::<A>(6);
                        let v = A::read(iq + 46, 2);
                        A::call(t, 6, &[2, 1, v as usize]);
                        let t = target::<A>(6);
                        let v = A::read(iq + 44, 2);
                        A::call(t, 6, &[3, 1, v as usize]);
                    } else if mode == 2 {
                        let t = target::<A>(6);
                        let v = A::read(dc + 6, 2);
                        A::call(t, 6, &[2, 2, v as usize]);
                        let t = target::<A>(6);
                        let v = A::read(dc + 4, 2);
                        A::call(t, 6, &[3, 2, v as usize]);
                        let packed = A::read(iq + 44, 4);
                        A::write(coefficients, 2, packed >> 16);
                        A::write(coefficients + 2, 2, packed);
                    } else {
                        call::<A>(6, &[2, 2, 256]);
                        call::<A>(6, &[3, 2, 256]);
                    }
                    let offset = if S3 {
                        channel_index * 2
                    } else {
                        channel * columns * 2 + col
                    };
                    let status = status_base + offset as usize;
                    call::<A>(
                        21,
                        &[
                            policy as usize,
                            mode as usize,
                            2048,
                            coefficients,
                            output,
                            status,
                        ],
                    );
                    let x = A::read(coefficients, 2);
                    let y = A::read(coefficients + 2, 2) as i16 as i32 as u32;
                    let packed = (x << 16) | y;
                    if mode == 1 {
                        A::write(dc + dc_index as usize * 4, 4, packed);
                        dc_index = (dc_index + 1) & 255;
                    } else if mode == 0 {
                        A::write(iq + iq_index as usize * 4, 4, packed);
                        iq_index = (iq_index + 1) & 255;
                    } else {
                        A::write(channels + offset as usize * 4, 4, packed);
                        A::write(
                            channels + (offset + if S3 { 1 } else { columns }) as usize * 4,
                            4,
                            packed,
                        );
                        let v = A::read(status, 1);
                        A::write(status + if S3 { 1 } else { columns as usize }, 1, v);
                        if S3 {
                            channel_index = (channel_index + 1) & 255;
                        }
                    }
                }
            }
            mode = (mode + 1) & 255;
        }
        if policy != 0 {
            i2c::<A>(Some(saved));
        } else {
            call::<A>(27, &[channels, status_base]);
        }
        call::<A>(3, &[0]);
        call::<A>(4, &[0]);
    }
}
include!("phy_rx_gain_cal_native.rs");
