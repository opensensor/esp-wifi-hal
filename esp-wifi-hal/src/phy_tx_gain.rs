//! Transmit-gain tables and programming, retaining the chip-specific PHY contracts.
//!
//! Pointer extents, channel indices and gain-table domains are supplied by the
//! original PHY callers. Calibration and ROM operations remain explicit calls.

pub(crate) trait Access {
    unsafe fn param() -> usize;
    unsafe fn global(kind: u32) -> usize;
    unsafe fn read(address: usize, width: usize) -> u32;
    unsafe fn write(address: usize, width: usize, value: u32);
    unsafe fn table() -> usize;
    unsafe fn slot(table: usize, offset: usize) -> usize;
    unsafe fn call(target: usize, args: &[usize], returns: bool) -> u32;
    unsafe fn external(kind: u32, args: &[usize]);
    unsafe fn log(kind: u32, args: &[u32]);
    unsafe fn local(pointer: *mut u32, tag: usize, size: usize) -> usize;
    unsafe fn copy(destination: usize, offset: usize, size: usize);
    unsafe fn child(kind: u32, args: &[usize]) -> u32;
}
const S3: bool = cfg!(esp32s3);
#[inline(always)]
fn byte(v: usize) -> u32 {
    if S3 { v as u8 as u32 } else { v as u32 }
}
#[inline(always)]
fn sb(v: u32) -> i32 {
    v as i8 as i32
}
#[inline(always)]
fn sh(v: u32) -> i32 {
    v as i16 as i32
}
#[inline(always)]
unsafe fn target<A: Access>(offset: usize) -> usize {
    unsafe { A::slot(A::table(), offset) }
}

#[inline(always)]
pub(crate) unsafe fn digital<A: Access>(input: usize) {
    unsafe {
        let p = A::param();
        let mut storage = core::mem::MaybeUninit::<[u32; 4]>::uninit();
        let b = A::local(storage.as_mut_ptr().cast(), 0, 16);
        for i in 0..14 {
            let x = A::read(input + i, 1);
            let y = A::read(p + i, 1);
            A::write(b + i, 1, x.wrapping_add(y));
        }
        for i in 0..2 {
            let x = A::read(b + i, 1);
            A::write(b + i, 1, x + if S3 { 3 } else { 4 });
        }
        for i in 10..14 {
            let x = A::read(b + i, 1);
            A::write(b + i, 1, x + if S3 { 3 } else { 2 });
        }
        if S3 {
            A::child(12, &[b]);
        } else {
            for i in 0..3 {
                let word = A::read(b + i * 4, 4);
                A::write(0x60006024 + i * 4, 4, word);
            }
            let high = sb(A::read(b + 13, 1)) as u32;
            let low = A::read(b + 12, 1);
            A::write(
                0x60006030,
                4,
                low | (high << 24) | ((high << 16) & 0x00ff0000) | ((high << 8) & 65535),
            );
        }
    }
}

#[inline(always)]
pub(crate) unsafe fn interpolate<A: Access>(input: usize, channel: u32) -> u32 {
    unsafe {
        let channel = byte(channel as usize);
        let left;
        let right;
        let origin;
        let bias;
        if S3 {
            if channel <= 37 {
                left = A::read(input, 1);
                right = A::read(input + 1, 1);
                origin = 12;
                bias = if channel <= 12 { -12 } else { 12 };
            } else {
                left = A::read(input + 1, 1);
                right = A::read(input + 2, 1);
                origin = 37;
                bias = 12;
            }
        } else {
            let middle = A::read(input + 1, 1);
            if channel <= 37 {
                left = A::read(input, 1);
                right = middle;
                origin = 12;
                bias = if channel <= 12 { -12 } else { 12 };
            } else {
                left = middle;
                right = A::read(input + 2, 1);
                origin = 37;
                bias = 12;
            }
        }
        let product = sb(right)
            .wrapping_sub(sb(left))
            .wrapping_mul(channel.wrapping_sub(origin) as i32);
        let result = (product.wrapping_add(bias) / 25).wrapping_add(sb(left));
        if S3 {
            result as u8 as u32
        } else {
            result as i8 as i32 as u32
        }
    }
}

#[inline(always)]
pub(crate) unsafe fn fcc<A: Access>(a: &[usize]) {
    unsafe {
        let channel = byte(a[0]);
        let p = a[2].wrapping_add(channel as usize);
        let first = A::read(p.wrapping_sub(1), 1);
        let second = A::read(p + 13, 1);
        let third = A::read(p + 27, 1);
        let index = if (channel.wrapping_sub(3) & 255) <= 8 {
            channel.wrapping_sub(3) as usize
        } else if channel < 3 {
            0
        } else {
            8
        };
        let fourth = A::read(a[3].wrapping_add(index), 1);
        for (i, value) in [first, second, third, fourth].into_iter().enumerate() {
            A::write(a[1] + i, 1, value.min(if S3 { 100 } else { 82 }));
        }
    }
}

#[inline(always)]
pub(crate) unsafe fn limits<A: Access>(a: &[usize]) {
    unsafe {
        let mut storage = core::mem::MaybeUninit::<[u32; 1]>::uninit();
        let b = A::local(storage.as_mut_ptr().cast(), 1, 4);
        A::copy(b, 0, 4);
        if byte(a[4]) == 1 {
            let args = [byte(a[0]) as usize, b, a[5], a[6]];
            if S3 {
                A::child(2, &args);
            } else {
                A::call(target::<A>(0x128), &args, false);
            }
        }
        let mut values = [0; 4];
        if S3 {
            for i in 0..4 {
                values[i] = A::read(b + i, 1);
            }
        } else {
            for i in (0..4).rev() {
                values[i] = A::read(b + i, 1);
            }
        }
        let cap = if S3 { sb(a[1] as u32) } else { a[1] as i32 };
        let p = A::param();
        for i in 0..14 {
            let input = A::read(a[3] + i, 1);
            A::write(a[2] + i, 1, input);
            let mut value = values[if i < 2 {
                0
            } else if i < 6 {
                1
            } else if i < 10 {
                2
            } else {
                3
            }] as i32;
            if !S3 {
                value = sb((value as u32).wrapping_sub(A::read(p + 0x217, 1)));
            }
            if value < sb(input) {
                A::write(a[2] + i, 1, value as u32);
            }
            let output = sb(A::read(a[2] + i, 1));
            if S3 || cap < output {
                A::write(a[2] + i, 1, cap.min(output) as u32);
            }
        }
    }
}

#[inline(always)]
pub(crate) unsafe fn lookup<A: Access>(a: &[usize]) -> u32 {
    unsafe {
        if !S3 {
            let mut scan = 0u32;
            let index = loop {
                let i = scan & 255;
                if i >= a[7] as u32 {
                    break (a[7] as u32).wrapping_sub(1) & 255;
                }
                scan = scan.wrapping_add(1);
                let threshold = sh(A::read(
                    a[6].wrapping_add(scan.wrapping_sub(1).wrapping_mul(2) as usize),
                    2,
                ));
                if (a[0] as i32) >= threshold {
                    break i;
                }
            } as usize;
            let code = A::read(a[4] + index, 1);
            A::write(a[1], 1, code);
            let value = A::read(a[5] + index * 2, 2);
            A::write(a[2], 2, value);
            let threshold = A::read(a[6] + index * 2, 2);
            A::write(a[3], 2, (a[0] as u32).wrapping_sub(threshold));
            0
        } else {
            let (mut index, count) = (a[0] as u8 as u32, a[9] as u8 as u32);
            let requested = sh(a[2] as u32);
            let adjustment = sh(a[1] as u32);
            let mut iterations = 0;
            while iterations != count {
                let threshold = sh(A::read(a[8] + index as usize * 2, 2));
                if requested >= threshold {
                    if index == 0 {
                        break;
                    }
                    let previous = sh(A::read(a[8] + index as usize * 2 - 2, 2));
                    if requested < previous {
                        break;
                    }
                    index = index.wrapping_sub(1) & 255;
                } else {
                    if index == count.wrapping_sub(1) {
                        break;
                    }
                    let next = sh(A::read(a[8] + index as usize * 2 + 2, 2));
                    index = (index + 1) & 255;
                    if requested >= next {
                        break;
                    }
                }
                iterations = (iterations + 1) & 255;
            }
            let threshold = A::read(a[8] + index as usize * 2, 2);
            let difference = sh((requested as u32).wrapping_sub(threshold));
            A::write(a[5], 2, difference as u32);
            if difference + adjustment > sb(a[10] as u32) && index != 0 {
                index = index.wrapping_sub(1) & 255;
            }
            let threshold = A::read(a[8] + index as usize * 2, 2);
            A::write(a[5], 2, (requested as u32).wrapping_sub(threshold));
            let code = A::read(a[6] + index as usize, 1);
            A::write(a[3], 1, code);
            let value = A::read(a[7] + index as usize * 2, 2);
            A::write(a[4], 2, value);
            index
        }
    }
}

#[cfg(any(feature = "esp32s3", esp32s3))]
#[inline(always)]
pub(crate) unsafe fn dig_check<A: Access>(value: usize, gain: usize) {
    unsafe {
        let input = A::read(value, 2);
        let table = A::table();
        let mut current = A::read(gain, 1);
        let mut index = A::call(A::slot(table, 0xdc), &[input as usize], true);
        let end = index.wrapping_add(4) & 255;
        while index < 4 && (current | current.wrapping_sub(1)) & 128 == 0 {
            index = index.wrapping_add(1) & 255;
            current = current.wrapping_sub(8) & 255;
            if index == end {
                break;
            }
        }
        let output = A::call(target::<A>(0xe0), &[index as usize], true);
        A::write(value, 2, output);
        A::write(gain, 2, sb(current) as u32);
    }
}

#[inline(always)]
pub(crate) unsafe fn bt_get<A: Access>(a: &[usize]) {
    unsafe {
        let mut storage = core::mem::MaybeUninit::<[u32; 4]>::uninit();
        let b = A::local(storage.as_mut_ptr().cast(), 2, 16);
        let delta = if S3 {
            sb(a[2] as u32) - sb(a[1] as u32)
        } else {
            (a[2] as i32).wrapping_sub(a[1] as i32)
        };
        let mut level = a[8] as i8 as i16 as u16 as u32;
        let step = (sb(a[9] as u32) * 4) as u16 as u32;
        let mut index = 0;
        for i in 0..16 {
            let power = A::call(
                target::<A>(0x28),
                &[sh(level) as usize, 80, (-96i32) as usize],
                true,
            );
            let input = sb(A::read(a[0] + 1, 1)) as u16 as u32;
            let requested = sh((delta as u32).wrapping_add(power));
            if S3 {
                index = A::child(
                    4,
                    &[
                        index as usize,
                        sh(0u32.wrapping_sub(input)) as usize,
                        requested as usize,
                        b,
                        b + 4,
                        b + 8,
                        a[3],
                        a[4],
                        a[5],
                        14,
                        (-8i32) as usize,
                    ],
                );
            } else {
                A::child(
                    4,
                    &[requested as usize, b, b + 4, b + 8, a[3], a[4], a[5], 14],
                );
            }
            let difference;
            let code;
            if S3 {
                difference = A::read(b + 8, 2);
                code = A::read(b, 1);
            } else {
                code = A::read(b, 1);
                difference = A::read(b + 8, 2);
            }
            let mut gain = sh(difference.wrapping_sub(input));
            if !S3 {
                gain = gain.min(24);
            }
            gain = gain.max(-64);
            A::write(a[7] + i, 1, code);
            A::write(a[6] + i, 1, gain as u32);
            if a[10] as u8 != 0 {
                let code = A::read(a[7] + i, 1);
                A::log(
                    0,
                    &[
                        i as u32,
                        code,
                        sb(gain as u32) as u32,
                        sh(difference) as u32,
                        sh(power) as u32,
                        requested as u32,
                    ],
                );
            }
            level = level.wrapping_add(step) & 65535;
        }
    }
}

#[inline(always)]
pub(crate) unsafe fn wifi_get<A: Access>(a: &[usize]) {
    unsafe {
        let mut storage = core::mem::MaybeUninit::<[u32; 4]>::uninit();
        let b = A::local(storage.as_mut_ptr().cast(), 3, 16);
        let mut power = if S3 {
            sb(A::call(
                target::<A>(0xfc),
                &[a[1], a[0] as u8 as usize],
                true,
            )) as u16 as u32
        } else {
            0
        };
        let mut index = 0;
        for i in 0..14 {
            if !S3 {
                power = A::call(target::<A>(0x110), &[a[1], a[0]], true);
            }
            let input = sb(A::read(a[2] + i, 1));
            let delta = if S3 {
                input - sb(a[3] as u32) + sb(a[4] as u32)
            } else {
                input.wrapping_sub(a[3] as i32).wrapping_add(a[4] as i32)
            };
            let requested = if S3 { delta } else { sh(delta as u32) };
            if S3 {
                index = A::child(
                    4,
                    &[
                        index as usize,
                        sh(0u32.wrapping_sub(power)) as usize,
                        requested as usize,
                        b,
                        b + 4,
                        b + 8,
                        a[5],
                        a[6],
                        a[7],
                        18,
                        0,
                    ],
                );
                let difference = A::read(b + 8, 2);
                let gain = sh(difference.wrapping_sub(power));
                A::write(b + 12, 2, gain as u32);
                if gain > 0 {
                    A::child(11, &[b + 4, b + 12]);
                }
                let gain = A::read(b + 12, 2);
                A::write(a[8] + i, 1, gain);
                let value = A::read(b + 4, 2);
                let code = A::read(b, 1);
                A::write(a[9] + i * 2, 2, value);
                A::write(a[10] + i, 1, code);
                if a[12] as u8 != 0 {
                    let gain = A::read(a[8] + i, 1);
                    let value = A::read(a[9] + i * 2, 2);
                    let input = A::read(a[2] + i, 1);
                    let difference = A::read(b + 8, 2);
                    A::log(
                        1,
                        &[
                            i as u32,
                            code,
                            value,
                            sb(gain) as u32,
                            sh(difference) as u32,
                            sb(input) as u32,
                            requested as u32,
                        ],
                    );
                }
            } else {
                A::child(
                    4,
                    &[requested as usize, b, b + 4, b + 8, a[5], a[6], a[7], 18],
                );
                let difference = sh(A::read(b + 8, 2));
                let value = A::read(b + 4, 2);
                A::write(a[9] + i * 2, 2, value);
                let code = A::read(b, 1);
                A::write(a[10] + i, 1, code);
                let gain = sh((difference as u32).wrapping_sub(power)).clamp(-80, 24);
                A::write(a[8] + i, 1, gain as u32);
                if a[12] as u8 != 0 {
                    let input = A::read(a[2] + i, 1);
                    let value = A::read(a[9] + i * 2, 2);
                    let code = A::read(a[10] + i, 1);
                    A::log(
                        1,
                        &[
                            i as u32,
                            code,
                            value,
                            gain as u32,
                            difference as u32,
                            sb(input) as u32,
                            requested as u32,
                        ],
                    );
                }
            }
        }
    }
}

#[inline(always)]
pub(crate) unsafe fn wifi_set<A: Access>(channel: usize, logging: usize) {
    unsafe {
        let p = A::param();
        let mut storage = core::mem::MaybeUninit::<[u32; 12]>::uninit();
        let b = A::local(storage.as_mut_ptr().cast(), 4, 48);
        let delta;
        if S3 {
            if A::read(p + 0x99, 1) != 0 {
                return;
            }
            let first = A::read(p + 0x1fb, 1);
            let second = A::read(p + 0x9a, 1);
            let cap = sb(A::read(p + 0x98, 1));
            delta = sb(first.wrapping_sub(second));
            let mode = A::read(p + 0x104, 1);
            A::child(
                3,
                &[
                    channel as u8 as usize,
                    cap as usize,
                    b + 32,
                    p + 0xf4,
                    mode as usize,
                    A::global(0),
                    p + 0x105,
                ],
            );
        } else {
            let first = sb(A::read(p + 0x1fb, 1));
            let second = sb(A::read(p + 0x9a, 1));
            delta = sb(first.wrapping_sub(second) as u32);
            for i in 0..14 {
                let v = A::read(p + 0xf4 + i, 1);
                A::write(b + i, 1, v);
            }
            if A::read(p + 0x99, 1) != 0 {
                return;
            }
            let mode = A::read(p + 0x104, 1);
            let cap = sb(A::read(p + 0x98, 1));
            A::child(
                3,
                &[
                    channel,
                    cap as usize,
                    b + 32,
                    b,
                    mode as usize,
                    A::global(0),
                    p + 0x105,
                ],
            );
        }
        let mut args = [
            byte(channel) as usize,
            p + 0x16f,
            b + 32,
            0,
            delta as usize,
            p + 14,
            p + 32,
            p + 68,
            p + 0x1ba,
            p + 0x1c8,
            p + 0x1e4,
            p,
            byte(logging) as usize,
        ];
        if S3 {
            let alternate = A::read(p + 0x2c8, 1);
            let table;
            if alternate == 1 {
                table = A::table();
                args[3] = sb(A::read(p + 0x2c9, 1)) as usize;
                args[1] = p + 0x2ca;
            } else {
                args[3] = sb(A::read(p + 0x175, 1)) as usize;
                table = A::table();
            }
            A::call(A::slot(table, 0x228), &args, false);
            A::call(
                target::<A>(0x210),
                &[0, 14, p + 0x1e4, p + 0x1c8, p + 0x124, p + 0x14c],
                false,
            );
            A::call(target::<A>(0x224), &[p + 0x1ba], false);
        } else {
            args[3] = sb(A::read(p + 0x175, 1)) as usize;
            A::child(6, &args);
            A::external(0, &[0, 14, p + 0x1e4, p + 0x1c8, p + 0x124, p + 0x14c]);
            A::child(0, &[p + 0x1ba]);
        }
    }
}

#[inline(always)]
pub(crate) unsafe fn bt_set<A: Access>(logging: usize) {
    unsafe {
        let p = A::param();
        let table;
        let first;
        let second;
        if S3 {
            table = A::table();
            first = A::read(p + 0x1fc, 1);
            second = A::read(p + 0x9a, 1);
        } else {
            table = 0;
            second = A::read(p + 0x9a, 1);
            first = A::read(p + 0x1fc, 1);
        }
        let gain = sb(A::read(p + 0x17c, 1));
        let args = [
            p + 0x179,
            gain as usize,
            sb(first.wrapping_sub(second)) as usize,
            p + 0x68,
            p + 32,
            p + 0x76,
            p + 0x1aa,
            p + 0x19a,
            (-96i32) as usize,
            3,
            byte(logging) as usize,
        ];
        if S3 {
            A::call(A::slot(table, 0x218), &args, false);
        } else {
            A::child(5, &args);
        }
        let args = [1, 16, p + 0x19a, p + 0x17e, p + 0x182, p + 0x180];
        if S3 {
            A::call(target::<A>(0x210), &args, false);
            A::call(target::<A>(0x214), &[p + 0x1aa], false);
        } else {
            A::external(0, &args);
            A::external(1, &[p + 0x1aa]);
        }
    }
}

#[inline(always)]
pub(crate) unsafe fn bt_initialize<A: Access>() {
    unsafe {
        A::external(2, &[]);
        A::external(3, &[]);
        A::external(4, &[]);
        if S3 {
            A::call(target::<A>(0x270), &[0], false);
        } else {
            A::child(8, &[0]);
        }
        A::external(5, &[A::param() + 0x179]);
    }
}

#[inline(always)]
pub(crate) unsafe fn calibration_tables<A: Access>() {
    unsafe {
        let mut storage = core::mem::MaybeUninit::<[u32; 56]>::uninit();
        let b = A::local(storage.as_mut_ptr().cast(), 5, 224);
        A::copy(b, 4, 18);
        if S3 {
            A::copy(b + 24, 22, 36);
            A::copy(b + 64, 58, 36);
            A::copy(b + 104, 94, 36);
            for i in 0..18 {
                A::write(b + 144 + i * 2, 2, 0);
            }
            A::write(b + 144, 2, 32);
            A::write(b + 146, 2, 256);
            A::write(b + 148, 2, 128);
            A::copy(b + 184, 130, 36);
        } else {
            for i in 0..8 {
                A::write(b + 28 + i * 4, 4, 0);
            }
            A::write(b + 24, 4, 0x00800100);
            A::copy(b + 64, 24, 36);
            A::copy(b + 104, 60, 14);
            A::copy(b + 120, 76, 28);
        }
        let p = A::param();
        let alternate = if S3 { A::read(p + 0x20d, 1) } else { 0 };
        for i in 0..18 {
            let code = A::read(
                if alternate == 1 {
                    b + 104 + i * 2
                } else {
                    b + i
                },
                1,
            );
            A::write(p + 14 + i, 1, code);
            let value = A::read(
                if alternate == 1 {
                    b + 144 + i * 2
                } else {
                    b + 24 + i * 2
                },
                2,
            );
            A::write(p + 32 + i * 2, 2, value);
            let threshold = A::read(
                if alternate == 1 {
                    b + 184 + i * 2
                } else {
                    b + 64 + i * 2
                },
                2,
            );
            A::write(p + 68 + i * 2, 2, threshold);
            if !S3 {
                let reference = A::read(p + 0x4e, 2);
                A::write(p + 68 + i * 2, 2, threshold.wrapping_sub(reference));
            }
        }
        if S3 {
            let index = if alternate == 1 { 6 } else { 8 };
            A::write(p + 0x20c, 1, index);
            let reference = sh(A::read(p + 68 + index as usize * 2, 2));
            for i in 0..18 {
                let threshold = A::read(p + 68 + i * 2, 2);
                A::write(p + 68 + i * 2, 2, threshold.wrapping_sub(reference as u32));
            }
        } else {
            A::write(p + 0xa3, 1, 5);
            for i in 0..14 {
                let code = A::read(b + 104 + i, 1);
                A::write(p + 0x68 + i, 1, code);
                let threshold = A::read(b + 120 + i * 2, 2);
                A::write(p + 0x76 + i * 2, 2, threshold);
                let reference = A::read(p + 0x80, 2);
                A::write(p + 0x76 + i * 2, 2, threshold.wrapping_sub(reference));
            }
            A::write(p + 0xa4, 1, 5);
        }
    }
}

#[cfg(esp32c3)]
pub(crate) const CONSTANTS: [u8; 104] = [
    82, 82, 82, 82, 127, 127, 127, 111, 95, 79, 119, 87, 115, 83, 53, 35, 19, 18, 48, 32, 16, 0, 0,
    0, 32, 0, 24, 0, 16, 0, 12, 0, 6, 0, 0, 0, 249, 255, 240, 255, 226, 255, 215, 255, 203, 255,
    193, 255, 178, 255, 169, 255, 157, 255, 146, 255, 132, 255, 108, 255, 127, 111, 95, 79, 63, 47,
    31, 15, 11, 7, 3, 2, 1, 0, 0, 0, 32, 0, 29, 0, 23, 0, 17, 0, 9, 0, 0, 0, 242, 255, 219, 255,
    209, 255, 194, 255, 170, 255, 161, 255, 148, 255, 124, 255,
];
#[cfg(esp32s3)]
pub(crate) const CONSTANTS: [u8; 166] = [
    100, 100, 100, 100, 127, 127, 127, 127, 127, 111, 95, 107, 119, 87, 115, 82, 81, 49, 48, 32,
    16, 0, 160, 0, 32, 0, 0, 1, 128, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 48, 0, 40, 0, 32, 0, 24, 0, 16, 0, 12, 0, 6, 0, 0, 0, 249, 255, 240,
    255, 226, 255, 203, 255, 193, 255, 178, 255, 157, 255, 146, 255, 132, 255, 108, 255, 127, 0,
    127, 0, 127, 0, 127, 0, 111, 0, 95, 0, 79, 0, 75, 0, 71, 0, 55, 0, 54, 0, 67, 0, 51, 0, 50, 0,
    19, 0, 6, 0, 3, 0, 2, 0, 40, 0, 32, 0, 24, 0, 16, 0, 12, 0, 6, 0, 0, 0, 246, 255, 232, 255,
    225, 255, 216, 255, 209, 255, 201, 255, 192, 255, 177, 255, 168, 255, 153, 255, 144, 255,
];

#[cfg(not(test))]
mod native {
    use super::{Access, CONSTANTS};
    unsafe extern "C" {
        static mut phy_param: u8;
        static mut g_phyFuns: *const u8;
        static mut chip7_phy_init_ctrl: u8;
        fn phy_printf(format: *const u8, ...);
        #[cfg(esp32c3)]
        fn rom_set_tx_gain_mem(a: usize, b: usize, c: usize, d: usize, e: usize, f: usize);
        #[cfg(esp32c3)]
        fn rom_bt_tx_dig_gain(a: usize);
        fn bt_txdc_cal();
        fn bt_txiq_cal();
        fn bt_tx_pwctrl_init();
        fn bt_txpwr_freq(a: usize);
        #[cfg(esp32s3)]
        fn __opensensor_reg_digital_gain(a: usize);
    }
    pub(super) struct Native;
    impl Access for Native {
        #[inline(always)]
        unsafe fn param() -> usize {
            (&raw const phy_param) as usize
        }
        #[inline(always)]
        unsafe fn global(_kind: u32) -> usize {
            (&raw const chip7_phy_init_ctrl) as usize
        }
        #[inline(always)]
        unsafe fn read(a: usize, w: usize) -> u32 {
            unsafe {
                match w {
                    1 => (a as *const u8).read_volatile().into(),
                    2 => (a as *const u16).read_volatile().into(),
                    4 => (a as *const u32).read_volatile(),
                    _ => unreachable!(),
                }
            }
        }
        #[inline(always)]
        unsafe fn write(a: usize, w: usize, v: u32) {
            unsafe {
                match w {
                    1 => (a as *mut u8).write_volatile(v as u8),
                    2 => (a as *mut u16).write_volatile(v as u16),
                    4 => (a as *mut u32).write_volatile(v),
                    _ => unreachable!(),
                }
            }
        }
        #[inline(always)]
        unsafe fn table() -> usize {
            unsafe { (&raw const g_phyFuns).read_volatile() as usize }
        }
        #[inline(always)]
        unsafe fn slot(t: usize, o: usize) -> usize {
            unsafe { ((t + o) as *const usize).read_volatile() }
        }
        #[inline(always)]
        unsafe fn call(t: usize, a: &[usize], returns: bool) -> u32 {
            unsafe {
                if returns {
                    match a.len() {
                        1 => core::mem::transmute::<usize, unsafe extern "C" fn(usize) -> u32>(t)(
                            a[0],
                        ),
                        2 => {
                            core::mem::transmute::<usize, unsafe extern "C" fn(usize, usize) -> u32>(
                                t,
                            )(a[0], a[1])
                        }
                        3 => core::mem::transmute::<
                            usize,
                            unsafe extern "C" fn(usize, usize, usize) -> u32,
                        >(t)(a[0], a[1], a[2]),
                        _ => unreachable!(),
                    }
                } else {
                    match a.len() {
                        1 => core::mem::transmute::<usize, unsafe extern "C" fn(usize)>(t)(a[0]),
                        4 => core::mem::transmute::<
                            usize,
                            unsafe extern "C" fn(usize, usize, usize, usize),
                        >(t)(a[0], a[1], a[2], a[3]),
                        6 => core::mem::transmute::<
                            usize,
                            unsafe extern "C" fn(usize, usize, usize, usize, usize, usize),
                        >(t)(a[0], a[1], a[2], a[3], a[4], a[5]),
                        11 => core::mem::transmute::<
                            usize,
                            unsafe extern "C" fn(
                                usize,
                                usize,
                                usize,
                                usize,
                                usize,
                                usize,
                                usize,
                                usize,
                                usize,
                                usize,
                                usize,
                            ),
                        >(t)(
                            a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7], a[8], a[9], a[10],
                        ),
                        13 => core::mem::transmute::<
                            usize,
                            unsafe extern "C" fn(
                                usize,
                                usize,
                                usize,
                                usize,
                                usize,
                                usize,
                                usize,
                                usize,
                                usize,
                                usize,
                                usize,
                                usize,
                                usize,
                            ),
                        >(t)(
                            a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7], a[8], a[9], a[10],
                            a[11], a[12],
                        ),
                        _ => unreachable!(),
                    };
                    0
                }
            }
        }
        #[inline(always)]
        unsafe fn external(k: u32, a: &[usize]) {
            unsafe {
                match k {
                    #[cfg(esp32c3)]
                    0 => rom_set_tx_gain_mem(a[0], a[1], a[2], a[3], a[4], a[5]),
                    #[cfg(esp32c3)]
                    1 => rom_bt_tx_dig_gain(a[0]),
                    2 => bt_txdc_cal(),
                    3 => bt_txiq_cal(),
                    4 => bt_tx_pwctrl_init(),
                    5 => bt_txpwr_freq(a[0]),
                    _ => unreachable!(),
                }
            }
        }
        #[inline(always)]
        unsafe fn log(k: u32, a: &[u32]) {
            unsafe {
                if k == 0 {
                    phy_printf(
                        c"%d,0x%x,%d, %d, power=%d, %d\n".as_ptr().cast(),
                        a[0],
                        a[1],
                        a[2],
                        a[3],
                        a[4],
                        a[5],
                    );
                } else {
                    phy_printf(
                        c"%d,0x%x,0x%x,%d, %d, power=%d, %d\n".as_ptr().cast(),
                        a[0],
                        a[1],
                        a[2],
                        a[3],
                        a[4],
                        a[5],
                        a[6],
                    );
                }
            }
        }
        #[inline(always)]
        unsafe fn local(p: *mut u32, _tag: usize, _size: usize) -> usize {
            p as usize
        }
        #[inline(always)]
        unsafe fn copy(d: usize, o: usize, n: usize) {
            unsafe {
                core::ptr::copy_nonoverlapping(CONSTANTS.as_ptr().add(o), d as *mut u8, n);
            }
        }
        #[inline(always)]
        unsafe fn child(k: u32, a: &[usize]) -> u32 {
            unsafe {
                match k {
                    0 => {
                        super::__opensensor_tx_gain_digital(a[0]);
                        0
                    }
                    1 => super::__opensensor_tx_gain_interpolate(a[0], a[1]),
                    2 => {
                        super::__opensensor_tx_gain_fcc(a[0], a[1], a[2], a[3]);
                        0
                    }
                    3 => {
                        super::__opensensor_tx_gain_limits(
                            a[0], a[1], a[2], a[3], a[4], a[5], a[6],
                        );
                        0
                    }
                    #[cfg(esp32c3)]
                    4 => super::__opensensor_tx_gain_lookup(
                        a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7],
                    ),
                    #[cfg(esp32s3)]
                    4 => super::__opensensor_tx_gain_lookup(
                        a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7], a[8], a[9], a[10],
                    ),
                    5 => {
                        super::__opensensor_tx_gain_bt_get(
                            a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7], a[8], a[9], a[10],
                        );
                        0
                    }
                    6 => {
                        super::__opensensor_tx_gain_wifi_get(
                            a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7], a[8], a[9], a[10],
                            a[11], a[12],
                        );
                        0
                    }
                    7 => {
                        super::__opensensor_tx_gain_wifi_set(a[0], a[1]);
                        0
                    }
                    8 => {
                        super::__opensensor_tx_gain_bt_set(a[0]);
                        0
                    }
                    9 => {
                        super::__opensensor_tx_gain_bt_initialize();
                        0
                    }
                    10 => {
                        super::__opensensor_tx_gain_calibration_tables();
                        0
                    }
                    #[cfg(esp32s3)]
                    11 => {
                        super::__opensensor_tx_gain_dig_check(a[0], a[1]);
                        0
                    }
                    #[cfg(esp32s3)]
                    12 => {
                        __opensensor_reg_digital_gain(a[0]);
                        0
                    }
                    _ => unreachable!(),
                }
            }
        }
    }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
#[unsafe(link_section = ".rwtext")]
pub unsafe extern "C" fn __opensensor_tx_gain_digital(a0: usize) {
    unsafe { digital::<native::Native>(a0) }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_tx_gain_interpolate(a0: usize, a1: usize) -> u32 {
    unsafe { interpolate::<native::Native>(a0, a1 as u32) }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_tx_gain_fcc(a0: usize, a1: usize, a2: usize, a3: usize) {
    unsafe { fcc::<native::Native>(&[a0, a1, a2, a3]) }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_tx_gain_limits(
    a0: usize,
    a1: usize,
    a2: usize,
    a3: usize,
    a4: usize,
    a5: usize,
    a6: usize,
) {
    unsafe { limits::<native::Native>(&[a0, a1, a2, a3, a4, a5, a6]) }
}

#[cfg(esp32c3)]
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_tx_gain_lookup(
    a0: usize,
    a1: usize,
    a2: usize,
    a3: usize,
    a4: usize,
    a5: usize,
    a6: usize,
    a7: usize,
) -> u32 {
    unsafe { lookup::<native::Native>(&[a0, a1, a2, a3, a4, a5, a6, a7]) }
}

#[cfg(esp32s3)]
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_tx_gain_lookup(
    a0: usize,
    a1: usize,
    a2: usize,
    a3: usize,
    a4: usize,
    a5: usize,
    a6: usize,
    a7: usize,
    a8: usize,
    a9: usize,
    a10: usize,
) -> u32 {
    unsafe { lookup::<native::Native>(&[a0, a1, a2, a3, a4, a5, a6, a7, a8, a9, a10]) }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_tx_gain_bt_get(
    a0: usize,
    a1: usize,
    a2: usize,
    a3: usize,
    a4: usize,
    a5: usize,
    a6: usize,
    a7: usize,
    a8: usize,
    a9: usize,
    a10: usize,
) {
    unsafe { bt_get::<native::Native>(&[a0, a1, a2, a3, a4, a5, a6, a7, a8, a9, a10]) }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_tx_gain_wifi_get(
    a0: usize,
    a1: usize,
    a2: usize,
    a3: usize,
    a4: usize,
    a5: usize,
    a6: usize,
    a7: usize,
    a8: usize,
    a9: usize,
    a10: usize,
    a11: usize,
    a12: usize,
) {
    unsafe { wifi_get::<native::Native>(&[a0, a1, a2, a3, a4, a5, a6, a7, a8, a9, a10, a11, a12]) }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_tx_gain_wifi_set(a0: usize, a1: usize) {
    unsafe { wifi_set::<native::Native>(a0, a1) }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
#[cfg_attr(esp32s3, unsafe(link_section = ".rwtext"))]
pub unsafe extern "C" fn __opensensor_tx_gain_bt_set(a0: usize) {
    unsafe { bt_set::<native::Native>(a0) }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_tx_gain_bt_initialize() {
    unsafe { bt_initialize::<native::Native>() }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_tx_gain_calibration_tables() {
    unsafe { calibration_tables::<native::Native>() }
}

#[cfg(esp32s3)]
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
pub unsafe extern "C" fn __opensensor_tx_gain_dig_check(a0: usize, a1: usize) {
    unsafe { dig_check::<native::Native>(a0, a1) }
}
