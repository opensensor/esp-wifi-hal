//! Receive DC searches with the original chip-specific fixed-point rules.
//! Estimation, PBUS access, delay and arithmetic callbacks remain boundaries.
#![allow(dead_code)]
pub(crate) trait Access {
    unsafe fn read(address: usize, width: usize) -> u32;
    unsafe fn write(address: usize, width: usize, value: u32);
    unsafe fn table_global() -> usize;
    unsafe fn coarse(index: u32) -> u32;
    unsafe fn local(pointer: *mut u32, tag: usize) -> usize;
    unsafe fn pbus_read(target: usize, block: u32, bank: u32) -> u32;
    unsafe fn force(target: usize, block: u32, bank: u32, value: u32);
    unsafe fn estimate(target: usize, samples: u32, output: usize);
    unsafe fn difference(target: usize, value: i32) -> i32;
    unsafe fn limit(target: usize, value: i32) -> i32;
    unsafe fn minimum(samples: u32, output: usize);
    unsafe fn delay(value: u32);
    unsafe fn log(kind: u32, args: &[u32]);
}
const S3: bool = cfg!(esp32s3);
const READ: usize = if S3 { 0x1ac } else { 0x1d0 };
const FORCE: usize = if S3 { 0x1a8 } else { 0x1cc };
const ESTIMATE: usize = if S3 { 0xf8 } else { 0x10c };
const ABS: usize = if S3 { 0xec } else { 0x100 };
#[inline(always)]
unsafe fn target<A: Access>(slot: usize) -> usize {
    unsafe { A::read(A::read(A::table_global(), 4) as usize + slot, 4) as usize }
}
#[inline(always)]
unsafe fn absolute<A: Access>(value: u32) -> i32 {
    unsafe { A::difference(target::<A>(ABS), value as i32) }
}
#[inline(always)]
unsafe fn force<A: Access>(block: u32, bank: u32, value: u32) {
    unsafe { A::force(target::<A>(FORCE), block, bank, value) }
}

/// `coefficients` spans four signed halfwords, with at least halfword alignment.
/// PBUS read(1,2)'s coarse-gain index must be in the pinned table's domain 0..6.
/// The estimator must initialize all three words in the supplied private buffer.
#[inline(always)]
pub(crate) unsafe fn general<A: Access>(
    samples: u32,
    coefficients: usize,
    delay: u32,
    summary: u32,
    detail: u32,
) {
    unsafe {
        let samples = if S3 { samples as u16 as u32 } else { samples };
        let delay = if S3 { delay as u16 as u32 } else { delay };
        let summary = if S3 { summary as u8 as u32 } else { summary };
        let detail = if S3 { detail as u8 as u32 } else { detail };
        let state = A::pbus_read(target::<A>(READ), 1, 2);
        let low = (state & 15).count_ones();
        let total = (state & 63).count_ones();
        let index = (state >> 6) & 255;
        force::<A>(2, 2, 256);
        force::<A>(3, 2, 256);
        let fine_shift = (if low == 0 { 4 } else { low + 5 }) + 2;
        let mut current = [
            (A::read(coefficients, 2) as i16).wrapping_mul(2) as i32,
            (A::read(coefficients + 2, 2) as i16).wrapping_mul(2) as i32,
        ];
        let mut storage = core::mem::MaybeUninit::<[u32; 3]>::uninit();
        let scratch = A::local(storage.as_mut_ptr().cast(), 0);
        for phase in 0..2 {
            let (threshold, budget) = if phase == 0 {
                (if total > 2 { 15 } else { 5 }, 12)
            } else {
                current = [512, 512];
                (if total > 3 { 5 } else { 2 }, 4)
            };
            let pointer = coefficients + phase * 4;
            let mut previous = [0u32; 2];
            let mut attempt = 0;
            while attempt < budget {
                for i in 0..2 {
                    let callback = target::<A>(FORCE);
                    let value = (current[i] + 1) >> 1;
                    A::write(pointer + i * 2, 2, value as u32);
                    A::force(
                        callback,
                        2 + i as u32,
                        phase as u32 + 1,
                        value as u16 as u32,
                    );
                }
                A::delay(delay);
                A::estimate(target::<A>(ESTIMATE), samples, scratch);
                if detail != 0 {
                    let second = A::read(pointer + 2, 2) as i16 as i32 as u32;
                    let first = A::read(pointer, 2) as i16 as i32 as u32;
                    A::log(0, &[first, second]);
                    A::log(1, &[A::read(scratch, 4), A::read(scratch + 4, 4)]);
                }
                if absolute::<A>(A::read(scratch, 4)) <= threshold
                    && absolute::<A>(A::read(scratch + 4, 4)) <= threshold
                {
                    break;
                }
                if attempt == 0 {
                    previous = [A::read(scratch, 4), A::read(scratch + 4, 4)];
                }
                let mut amount = total + 6;
                for i in 0..2 {
                    let address = scratch + i * 4;
                    if absolute::<A>(A::read(address, 4)) > threshold {
                        let delta = if phase != 0 {
                            (A::read(address, 4) as i32)
                                .wrapping_mul(280)
                                .wrapping_shr(fine_shift)
                        } else {
                            let distance =
                                absolute::<A>(A::read(address, 4).wrapping_sub(previous[i]));
                            let scaled = (A::read(address, 4) as i32).wrapping_mul(3) / 2;
                            if absolute::<A>(scaled as u32) < distance {
                                amount = (amount + 1) & 255;
                            }
                            (A::coarse(index)
                                .wrapping_mul(A::read(address, 4))
                                .wrapping_mul(6) as i32)
                                .wrapping_shr(amount + 2)
                        };
                        current[i] = current[i].wrapping_sub(delta) as i16 as i32;
                    }
                }
                current = [current[0].clamp(0, 1022), current[1].clamp(0, 1022)];
                previous = [A::read(scratch, 4), A::read(scratch + 4, 4)];
                attempt += 1;
            }
            if summary != 0 {
                A::log(
                    2,
                    &[
                        phase as u32 + 1,
                        total,
                        index,
                        A::read(scratch, 4),
                        A::read(scratch + 4, 4),
                        attempt,
                    ],
                );
            }
            if detail != 0 {
                A::log(3, &[]);
            }
        }
        if summary != 0 {
            A::log(3, &[]);
        }
    }
}

/// `coefficients` spans two halfwords (S3 callers can be only 2-byte aligned).
/// `output` spans three aligned words and `status` one byte. Access stays raw
/// to preserve observable in-place overlap and callback mutation behavior.
#[inline(always)]
pub(crate) unsafe fn one_step<A: Access>(
    policy: u32,
    mode: u32,
    samples: u32,
    coefficients: usize,
    output: usize,
    status: usize,
) {
    unsafe {
        let policy = if S3 { policy as u8 as u32 } else { policy };
        let mode = if S3 { mode as u8 as u32 } else { mode };
        let samples = if S3 { samples as u16 as u32 } else { samples };
        let mut first = A::read(coefficients, 2) as i16 as i32;
        let mut second = A::read(coefficients + 2, 2) as i16 as i32;
        let mut zero_storage = [0u32; 3];
        let mut set_storage = [0u32; 3];
        let zero = A::local(zero_storage.as_mut_ptr(), 0);
        let set = A::local(set_storage.as_mut_ptr(), 1);
        // Explicit Access writes also initialize the host's mapped local buffers.
        A::write(zero, 4, 0);
        A::write(zero + 4, 4, 0);
        A::write(zero + 8, 4, 0);
        A::write(set, 4, 0);
        A::write(set + 4, 4, 0);
        A::write(set + 8, 4, 0);
        let state = A::pbus_read(target::<A>(READ), 1, 2) as u8;
        let backup = A::pbus_read(target::<A>(READ), 0, 1);
        let gain = (state & 63).count_ones();
        let threshold = if mode == 1 {
            gain.saturating_sub(1).max(1)
        } else if policy != 0 {
            if S3 { 10 } else { 6 }
        } else {
            1
        } as i32;
        let bank = if mode == 1 { 2 } else { 1 };
        let budget = if mode == 1 { 8 } else { 16 };
        A::write(status, 1, 0);
        for _ in 0..budget {
            let callback = target::<A>(FORCE);
            let saved = first as u16 as u32;
            A::write(coefficients, 2, first as u32);
            A::write(coefficients + 2, 2, second as u32);
            A::force(callback, 2, bank, saved);
            let callback = target::<A>(FORCE);
            let value = A::read(coefficients + 2, 2);
            A::force(callback, 3, bank, value);
            let (score, amount) = if mode == 1 {
                A::delay(10);
                A::minimum(samples, output);
                (A::read(output + 8, 4) as i32, gain.saturating_sub(1))
            } else {
                force::<A>(1, 2, 0);
                A::delay(10);
                A::minimum(samples, zero);
                force::<A>(1, 2, 32);
                A::delay(10);
                A::minimum(samples, set);
                let dx = A::read(set, 4).wrapping_sub(A::read(zero, 4));
                let dy = A::read(set + 4, 4).wrapping_sub(A::read(zero + 4, 4));
                if S3 {
                    A::write(output + 4, 4, dy);
                    A::write(output, 4, dx);
                } else {
                    A::write(output, 4, dx);
                    A::write(output + 4, 4, dy);
                }
                let score = (A::read(zero + 8, 4) as i32).max(A::read(set + 8, 4) as i32);
                (
                    score,
                    if policy != 0 {
                        3
                    } else {
                        (absolute::<A>(dx) < 5) as u32
                    },
                )
            };
            let mut changes = [0i32; 2];
            for i in 0..2 {
                if absolute::<A>(A::read(output + i * 4, 4)) >= threshold {
                    changes[i] =
                        (A::read(output + i * 4, 4) as i32).wrapping_shr(amount) as i16 as i32;
                }
            }
            for i in 0..2 {
                if changes[i] == 0 {
                    changes[i] = if absolute::<A>(A::read(zero + i * 4, 4)) > 49 {
                        (A::read(zero + i * 4, 4) as i32).wrapping_shr(amount) as i16 as i32
                    } else {
                        (A::read(output + i * 4, 4) as i32).signum()
                    };
                }
            }
            if mode != 1 {
                if score > 44 {
                    changes = [0, 0];
                } else if !S3 && absolute::<A>(A::read(output, 4)) <= 9 {
                    // C3 executes this callback even though its result is unused.
                    absolute::<A>(A::read(output + 4, 4));
                }
                if backup > 436 {
                    for change in &mut changes {
                        *change = A::limit(target::<A>(40), *change) as i16 as i32;
                    }
                }
            }
            if absolute::<A>(A::read(output, 4)) <= threshold
                && absolute::<A>(A::read(output + 4, 4)) <= threshold
                && score <= 45
            {
                A::write(status, 1, 1);
                break;
            }
            if absolute::<A>(A::read(output, 4)) > threshold {
                first = saved.wrapping_sub(changes[0] as u32) as i16 as i32;
            }
            if absolute::<A>(A::read(output + 4, 4)) > threshold {
                second = second.wrapping_sub(changes[1]) as i16 as i32;
            }
            first = first.clamp(0, 511);
            second = second.clamp(0, 511);
        }
        // Exhaustion keeps the last written pair, not the uncommitted update.
        for i in 0..2 {
            let value = A::read(coefficients + i * 2, 2) as i16 as i32;
            if !(0..=511).contains(&value) {
                A::write(coefficients + i * 2, 2, value.clamp(0, 511) as u32);
            }
        }
        for i in 0..2 {
            let callback = target::<A>(FORCE);
            let value = A::read(coefficients + i * 2, 2);
            A::force(callback, 2 + i as u32, bank, value);
        }
    }
}
include!("phy_dc_search_native.rs");
