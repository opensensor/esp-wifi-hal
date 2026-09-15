//! TX IQ measurement and attenuation search with chip-specific machine boundaries.
pub trait Access {
    const S3: bool;
    fn read_register(&mut self, address: u32) -> u32;
    fn write_register(&mut self, address: u32, value: u32);
    fn write_sample(&mut self, address: u32, value: u16);
    fn delay(&mut self);
    fn linear(&mut self) -> i32;
    fn tone(&mut self, tone: i32, code: u8);
    fn power_db(&mut self, offset: u32) -> i32;
    fn log(&mut self, iteration: i32, attenuation: i32, sample: i32, target: i32, delta: i32);
    fn limit(&mut self, delta: i32) -> i32;
}

#[inline(always)]
pub fn measure<A: Access>(
    a: &mut A,
    select: u32,
    negative: u32,
    offset: i32,
    out1: u32,
    out2: u32,
) {
    let select = if A::S3 { select as u8 as u32 } else { select };
    let offset = if A::S3 { offset as i16 as i32 } else { offset };
    let fields = ((select << 26)
        | ((negative.wrapping_neg() << 10) & 0x3fc00)
        | ((offset >> 2) as u32)
        | 0x2c0000)
        & 0x0fff_ffff;
    let old = a.read_register(0x60006040);
    a.write_register(0x60006040, (old & 0xf0000000) | fields);
    let old = a.read_register(0x60006050);
    a.write_register(0x60006050, (old & !3) | (offset as u32 & 3));
    a.delay();
    let sample = a.linear();
    a.write_sample(out1, sample as u16);
    let old = a.read_register(0x60006040);
    a.write_register(
        0x60006040,
        (old & 0xf0ffffff) | ((((!select & 1) | (select << 3)) << 24) & 0x0f000000),
    );
    a.delay();
    let sample = a.linear();
    a.write_sample(out2, sample as u16);
}

#[inline(always)]
pub fn attenuation<A: Access>(
    a: &mut A,
    tone: i32,
    attenuation: i32,
    target: i32,
    offset: u32,
    debug: u32,
) -> i32 {
    let tone = if A::S3 { tone as i16 as i32 } else { tone };
    let mut attenuation = if A::S3 {
        attenuation as i8 as i32
    } else {
        attenuation
    };
    let target = if A::S3 { target as u8 as i32 } else { target };
    let offset = if A::S3 { offset as u16 as u32 } else { offset };
    let debug = if A::S3 { debug as u8 as u32 } else { debug };
    let (mut previous_attenuation, mut previous_sample) = (0, 0);
    for iteration in 0..6 {
        a.tone(tone, attenuation as u8);
        if A::S3 {
            a.delay();
        }
        let sample = (a.power_db(offset) >> 2) as i16 as i32;
        let delta = sample.wrapping_sub(target) as i16 as i32;
        if iteration != 0 && previous_attenuation < attenuation && previous_sample < sample {
            attenuation = previous_attenuation.wrapping_sub(20) as i16 as i32;
        }
        if debug != 0 {
            a.log(iteration, attenuation, sample, target, delta);
        }
        if (delta.wrapping_add(3) as u16) <= 6 {
            return attenuation;
        }
        let adjustment = if A::S3 {
            delta
        } else {
            a.limit(delta) as i16 as i32
        };
        let adjustment = if adjustment > 0 {
            adjustment
        } else {
            adjustment * 3 / 4
        };
        let next = attenuation.wrapping_add(adjustment) as i16 as i32;
        if next < 0 {
            return 0;
        }
        if next > 120 {
            return 120;
        }
        previous_attenuation = attenuation;
        previous_sample = sample;
        attenuation = next;
    }
    attenuation
}

#[cfg(all(not(test), any(target_arch = "xtensa", target_arch = "riscv32")))]
include!("phy_tx_iq_measure_native.rs");
