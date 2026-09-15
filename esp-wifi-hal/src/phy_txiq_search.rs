//! TX IQ correction search and calibration orchestration.
pub trait Access {
    const S3: bool;
    fn read(&mut self, address: u32, width: usize) -> u32;
    fn write(&mut self, address: u32, width: usize, value: u32);
    fn parameter(&mut self, offset: usize, width: usize) -> u32;
    fn table(&mut self) -> u32;
    fn slot(&mut self, table: u32, offset: u32) -> u32;
    fn call1(&mut self, callback: u32, a: u32) -> u32;
    fn call2(&mut self, callback: u32, a: u32, b: u32) -> u32;
    fn call3(&mut self, callback: u32, a: u32, b: u32, c: u32) -> u32;
    fn set_correction(&mut self, code: i32, select: u32) -> i32;
    fn measure(&mut self, select: u32, attenuation: u32, tone: i32);
    fn sample(&mut self, index: usize) -> i16;
    fn debug_mode(&mut self);
    fn work_mode(&mut self);
    fn txdc(&mut self, dc_buffer: u32);
    fn attenuation(&mut self, tone: i32, initial: i32, target: i32, offset: u32) -> i32;
    fn cover(&mut self, attenuation: u8, tone: i32);
    fn coefficient(&mut self, index: usize) -> u8;
    fn write_coefficient(&mut self, index: usize, value: u8);
}
#[inline(always)]
fn code_argument<A: Access>(code: i32) -> i32 {
    if A::S3 {
        code as i8 as i32
    } else {
        code
    }
}
#[inline(always)]
pub fn search<A: Access>(a: &mut A, attenuation: u32, tone: i32, out: u32) {
    let attenuation = if A::S3 {
        attenuation & 255
    } else {
        attenuation
    };
    let tone = if A::S3 { tone as i16 as i32 } else { tone };
    let reduced = (attenuation.wrapping_sub(12) as i8).max(0) as u32;
    let mut first = 0i32;
    let mut second = 0i32;
    let mut sum_first = 0i8;
    let mut sum_second = 0i8;
    for iteration in 0..7 {
        first = a.set_correction(code_argument::<A>(first), 1);
        if A::S3 {
            first = first as u8 as i32;
        }
        second = a.set_correction(code_argument::<A>(second), 0);
        if A::S3 {
            second = second as u8 as i32;
        }
        a.measure(1, reduced, tone);
        let (x, y) = if A::S3 {
            let x = a.sample(0) as i32;
            let y = a.sample(1) as i32;
            (x, y)
        } else {
            let y = a.sample(1) as i32;
            let x = a.sample(0) as i32;
            (x, y)
        };
        let denominator = x.min(y);
        let denominator = if denominator == 0 { 1 } else { denominator };
        let correction = ((((y - x) * 2048) / denominator + 16) >> 5) as u8;
        a.write(out, 1, correction as u32);
        a.measure(0, attenuation, tone);
        let x = a.sample(0) as i32;
        let y = a.sample(1) as i32;
        let denominator = (x + y) as i16 as i32;
        let denominator = if denominator == 0 { 1 } else { denominator };
        let correction = ((((x - y) * 4096) / denominator + 16) >> 5) as u8;
        let delta_first;
        if A::S3 {
            a.write(out + 1, 1, correction as u32);
            delta_first = a.read(out, 1) as u8;
        } else {
            delta_first = a.read(out, 1) as u8;
            a.write(out + 1, 1, correction as u32);
        }
        if iteration < 3 {
            first = first.wrapping_sub(delta_first as i32) as i8 as i32;
            second = second.wrapping_sub(correction as i32) as i8 as i32;
        } else {
            sum_first = sum_first.wrapping_add(delta_first as i8);
            sum_second = sum_second.wrapping_add(correction as i8);
            let table = a.table();
            let slot = if A::S3 { 0xec } else { 0x100 };
            let callback = a.slot(table, slot);
            let magnitude = a.call1(callback, delta_first as i8 as i32 as u32) as i32;
            if magnitude <= 1 {
                let table = a.table();
                let delta_second = a.read(out + 1, 1) as u8 as i8 as i32;
                let callback = a.slot(table, slot);
                if (a.call1(callback, delta_second as u32) as i32) <= 1 {
                    break;
                }
            }
            if iteration == 6 {
                first = first.wrapping_sub((sum_first as i32 + 2) >> 2) as i8 as i32;
                second = second.wrapping_sub((sum_second as i32 + 2) >> 2) as i8 as i32;
            }
        }
    }
    a.set_correction(code_argument::<A>(first), 1);
    a.set_correction(code_argument::<A>(second), 0);
    if A::S3 {
        a.write(out, 1, first as u8 as u32);
        a.write(out + 1, 1, second as u8 as u32);
    } else {
        a.write(out + 1, 1, second as u8 as u32);
        a.write(out, 1, first as u8 as u32);
    }
}
#[inline(always)]
fn target<A: Access>(a: &mut A, offset: u32) -> u32 {
    let table = a.table();
    a.slot(table, offset)
}
#[inline(always)]
pub fn calibrate<A: Access>(
    a: &mut A,
    initial: u32,
    dc: u32,
    iq: u32,
    tone: u32,
    attenuation: u32,
    mode: u32,
) {
    let s3 = A::S3;
    let power_target = if s3 {
        56
    } else {
        let selector = a.parameter(162, 1) as u8;
        if selector.wrapping_sub(16) <= 1 {
            30
        } else {
            56
        }
    };
    let initial = if s3 { initial & 65535 } else { initial };
    let mode = if s3 { mode & 255 } else { mode };
    let tone = if s3 {
        tone as u8 as i32
    } else {
        tone as i16 as i32
    };
    let attenuation = if s3 {
        attenuation as i8 as i32
    } else {
        attenuation as i32
    };
    let value = a.read(0x6000607c, 4);
    a.write(0x6000607c, 4, value | 0x800);
    let value = a.read(0x6000607c, 4);
    a.write(0x6000607c, 4, value & !0x1000);
    a.debug_mode();
    let (write_slot, read_slot, dc_slot) = if s3 {
        (0x1a8, 0x1ac, 0x1cc)
    } else {
        (0x1cc, 0x1d0, 0x1f0)
    };
    let f = target(a, write_slot);
    a.call3(f, 1, 2, initial);
    if mode == 1 {
        let table = a.table();
        let write = a.slot(table, write_slot);
        let read = a.slot(table, read_slot);
        let value = a.call2(read, 1, 1);
        a.call3(write, 1, 1, (value | 2) & 65535);
        if s3 {
            let f = target(a, write_slot);
            a.call3(f, 4, 2, 24);
        }
    }
    if mode == 2 {
        let f = target(a, 36);
        a.call1(f, 1);
        a.txdc(dc);
    } else {
        let f = target(a, dc_slot);
        a.call1(f, dc);
    }
    let offset = if s3 { 224 } else { a.parameter(832, 2) };
    let saved = a.read(0x60006040, 4);
    let code = a.attenuation(tone, attenuation, power_target, offset);
    a.cover(code as u8, tone);
    a.work_mode();
    for (index, limit) in [(0, 15i8), (1, 31)] {
        let value = a.coefficient(index) as i8;
        if value > limit {
            a.write_coefficient(index, limit as u8);
        } else if value < -limit {
            a.write_coefficient(index, (-limit) as u8);
        }
    }
    let first = a.coefficient(0) as u32;
    let second = a.coefficient(1) as u32;
    a.write(iq, 2, ((first & 31) << 6) | (second & 63));
    a.write(0x60006040, 4, saved);
    if mode == 2 {
        let f = target(a, 36);
        a.call1(f, 0);
    }
    let value = a.read(0x6000607c, 4);
    a.write(0x6000607c, 4, value | 0x1000);
}

#[cfg(all(not(test), any(target_arch = "xtensa", target_arch = "riscv32")))]
include!("phy_txiq_search_native.rs");
