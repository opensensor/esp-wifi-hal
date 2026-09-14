#![allow(dead_code)]
use std::{cell::RefCell, fs};
#[path = "../../../esp-wifi-hal/src/phy_track.rs"]
mod production;
const S3: bool = cfg!(esp32s3);
const BUSY: usize = if S3 { 0x2a4 } else { 0x321 };
#[derive(Debug)]
struct BoundaryStop;
struct State {
    case: [u32; 32],
    memory: [u8; 848],
    trace: Vec<u32>,
    generation: u32,
    calls: u32,
    abs_calls: usize,
    conversions: usize,
    polls: u32,
}
fn fields() -> Vec<(usize, usize)> {
    let mut v = vec![];
    for o in [
        0x204,
        0x9b,
        0x9f,
        0xa0,
        0x1fa,
        0x1fb,
        0x1fc,
        0x1f2,
        BUSY,
        BUSY + 4,
    ] {
        v.push((o, 1));
    }
    for o in [0x92, 0x94, 0x96, 0xae, 0xb0, 0xb2, 0xb4] {
        v.push((o, 2));
    }
    for o in if S3 {
        vec![0x206, 0x208, 0x2c4, 0x2c6]
    } else {
        vec![0x20c, 0x20e, 0x210, 0x212, 0x214]
    } {
        v.push((o, 2));
    }
    v.extend([(0x120, 4), (0x200, 4)]);
    v
}
fn arity(slot: usize) -> usize {
    if S3 {
        match slot {
            0xec => 1,
            0x28 => 3,
            0x188 => 3,
            0x190 => 4,
            0x198 => 6,
            0x204 | 0x200 => 0,
            0x194 => 5,
            0x104 => 2,
            0x240 => 1,
            0x264 => 2,
            0x270 => 1,
            0x268 => 3,
            _ => panic!("unknown slot {slot:x}"),
        }
    } else {
        match slot {
            0x100 => 1,
            0x28 => 3,
            0x1ac => 3,
            0x1b4 => 4,
            0x1bc => 6,
            0x228 | 0x224 | 8 | 12 => 0,
            0x118 => 2,
            _ => panic!("unknown slot {slot:x}"),
        }
    }
}
impl State {
    fn get(&self, o: usize, w: usize) -> u32 {
        (0..w).fold(0, |v, i| v | (u32::from(self.memory[o + i]) << (i * 8)))
    }
    fn put(&mut self, o: usize, w: usize, v: u32) {
        for i in 0..w {
            self.memory[o + i] = (v >> (i * 8)) as u8;
        }
    }
    fn new(c: [u32; 32]) -> Self {
        let mut s = Self {
            case: c,
            memory: [0; 848],
            trace: vec![],
            generation: 0,
            calls: 0,
            abs_calls: 0,
            conversions: 0,
            polls: 0,
        };
        for (o, i, shift) in [
            (0x92, 19, 0),
            (0x94, 19, 16),
            (0x96, 20, 0),
            (if S3 { 0x2c6 } else { 0x212 }, 20, 16),
            (if S3 { 0x206 } else { 0x20c }, 21, 0),
            (if S3 { 0x208 } else { 0x20e }, 21, 16),
            (if S3 { 0x2c4 } else { 0x210 }, 22, 0),
            (0xae, 23, 0),
            (0xb0, 23, 16),
            (0xb2, 24, 0),
            (0xb4, 24, 16),
        ] {
            s.put(o, 2, c[i] >> shift);
        }
        if !S3 {
            s.put(0x214, 2, c[22] >> 16);
        }
        for (o, i, shift) in [
            (0x204, 25, 0),
            (0x9b, 25, 8),
            (0x9f, 25, 16),
            (0xa0, 25, 24),
            (0x1fa, 26, 0),
            (0x1fb, 26, 8),
            (0x1fc, 26, 16),
            (0x1f2, 26, 24),
            (BUSY, 27, 0),
            (BUSY + 4, 27, 8),
        ] {
            s.put(o, 1, c[i] >> shift);
        }
        s.put(0x120, 4, c[28]);
        s.put(0x200, 4, c[18]);
        s
    }
    fn event(&mut self, kind: u32, args: &[u32]) {
        assert!(args.len() <= 7 && self.trace.len() < 512 * 8);
        self.trace.push(kind);
        self.trace.extend_from_slice(args);
        self.trace.extend(std::iter::repeat_n(0, 7 - args.len()));
    }
    fn mutate(&mut self) {
        assert!(self.calls < 32);
        if self.case[14] & (1 << self.calls) != 0 {
            self.generation += 1;
        }
        if self.case[15] & (1 << self.calls) != 0 {
            for (o, w) in fields() {
                self.put(
                    o,
                    w,
                    self.get(o, w) ^ self.case[29].wrapping_add(o as u32 * 17),
                );
            }
        }
        self.calls += 1;
    }
    fn read(&mut self, o: usize, w: usize) -> u32 {
        assert!(fields().contains(&(o, w)));
        let v = self.get(o, w);
        self.event(1, &[0x200000 + o as u32, w as u32, v]);
        v
    }
    fn write(&mut self, o: usize, w: usize, v: u32) {
        assert!(fields().contains(&(o, w)));
        self.event(2, &[0x200000 + o as u32, w as u32, v]);
        self.put(o, w, v);
    }
    fn callback(&mut self, target: usize, args: &[u32]) -> Option<u32> {
        assert!((0x71000000..0x71040000).contains(&target));
        let slot = (target - 0x71000000) % 0x1000;
        let generation = (target - 0x71000000) / 0x1000;
        assert!(generation <= self.generation as usize);
        assert_eq!(args.len(), arity(slot));
        let mut a = vec![target as u32];
        a.extend_from_slice(args);
        self.event(6, &a);
        if S3 && slot == 0x268 && self.case[16] & 8 != 0 {
            return None;
        }
        let value = if slot == if S3 { 0xec } else { 0x100 } {
            let v = self.case[4 + self.abs_calls.min(1)];
            self.abs_calls += 1;
            v
        } else if slot == 0x28 {
            self.case[6]
        } else if slot == if S3 { 0x104 } else { 0x118 } {
            let v = self.case[9 + self.conversions.min(1)];
            self.conversions += 1;
            v
        } else if slot == if S3 { 0x188 } else { 0x1ac } || (S3 && slot == 0x194) {
            self.case[7]
        } else {
            self.case[13]
        };
        self.mutate();
        Some(value)
    }
}
thread_local! { static STATE:RefCell<State>=RefCell::new(State::new([0;32])); }
struct Access;
impl production::Access for Access {
    unsafe fn param() -> usize {
        0x200000
    }
    unsafe fn read8(o: usize) -> u8 {
        STATE.with_borrow_mut(|s| s.read(o, 1) as u8)
    }
    unsafe fn read16(o: usize) -> u16 {
        STATE.with_borrow_mut(|s| s.read(o, 2) as u16)
    }
    unsafe fn read32(o: usize) -> u32 {
        STATE.with_borrow_mut(|s| s.read(o, 4))
    }
    unsafe fn write8(o: usize, v: u8) {
        STATE.with_borrow_mut(|s| s.write(o, 1, v.into()));
    }
    unsafe fn write16(o: usize, v: u16) {
        STATE.with_borrow_mut(|s| s.write(o, 2, v.into()));
    }
    unsafe fn write32(o: usize, v: u32) {
        STATE.with_borrow_mut(|s| s.write(o, 4, v));
    }
    unsafe fn busy() -> u32 {
        STATE.with_borrow_mut(|s| {
            if s.polls == 64 {
                std::panic::panic_any(BoundaryStop);
            }
            let v = (s.case[30] & 0x7fffffff) | if s.polls < s.case[17] { 1 << 31 } else { 0 };
            s.polls += 1;
            s.event(7, &[0x6000e168, v]);
            v
        })
    }
    unsafe fn table() -> usize {
        STATE.with_borrow_mut(|s| {
            s.event(4, &[s.generation]);
            0x70000000 + s.generation as usize * 0x1000
        })
    }
    unsafe fn slot(table: usize, offset: usize) -> usize {
        STATE.with_borrow_mut(|s| {
            assert!((0x70000000..0x70040000).contains(&table));
            assert_eq!((table - 0x70000000) % 0x1000, 0);
            let generation = (table - 0x70000000) / 0x1000;
            assert!(generation <= s.generation as usize);
            arity(offset);
            s.event(5, &[offset as u32, generation as u32]);
            0x71000000 + generation * 0x1000 + offset
        })
    }
    unsafe fn read_call<const N: usize>(target: usize, args: [u32; N]) -> u32 {
        STATE.with_borrow_mut(|s| s.callback(target, &args).expect("unexpected nested read"))
    }
    unsafe fn write_call<const N: usize>(target: usize, args: [u32; N]) {
        let result = STATE.with_borrow_mut(|s| s.callback(target, &args));
        if result.is_none() {
            unsafe {
                production::power_track::<Self>(args[0], args[1], args[2]);
            }
        }
    }
    unsafe fn external(kind: u32, args: [u32; 4]) -> u32 {
        STATE.with_borrow_mut(|s| {
            let arity = match kind {
                0 => 1,
                1 => 0,
                2 => {
                    if S3 {
                        2
                    } else {
                        3
                    }
                }
                3 => 2,
                4 => 4,
                5 => 2,
                6 | 7 => 1,
                _ => panic!("unknown helper"),
            };
            let mut a = vec![kind];
            a.extend_from_slice(&args[..arity]);
            s.event(10, &a);
            let result = match kind {
                1 => s.case[8],
                2 => s.case[11],
                3 => s.case[12],
                _ => s.case[13],
            };
            s.mutate();
            result
        })
    }
    unsafe fn internal(kind: u32, args: [u32; 3]) {
        let nested = STATE.with_borrow_mut(|s| {
            let arity = match kind {
                0 => 0,
                1 => 2,
                2 => 1,
                _ => panic!("unknown internal"),
            };
            let mut a = vec![kind];
            a.extend_from_slice(&args[..arity]);
            s.event(9, &a);
            if s.case[16] & (1 << kind) != 0 {
                true
            } else {
                s.mutate();
                false
            }
        });
        if nested {
            unsafe {
                match kind {
                    0 => production::wait::<Self>(),
                    1 => production::ulp_set::<Self>(args[0], args[1]),
                    2 => production::ulp_track::<Self>(args[0]),
                    _ => unreachable!(),
                }
            }
        }
    }
    unsafe fn print(kind: u32, args: [u32; 4]) {
        STATE.with_borrow_mut(|s| {
            let arity = match kind {
                0 | 3 => 2,
                1 | 2 => {
                    if S3 {
                        4
                    } else {
                        3
                    }
                }
                _ => panic!("unknown format"),
            };
            let mut a = vec![kind];
            a.extend_from_slice(&args[..arity]);
            s.event(12, &a);
            s.mutate();
        });
    }
}
#[test]
fn original_instruction_boundaries() {
    let hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        if !info.payload().is::<BoundaryStop>() {
            hook(info)
        }
    }));
    let raw = fs::read(std::env::var("PHY_TRACK_CASES").expect("corpus")).unwrap();
    assert_eq!(raw.len() % 4, 0);
    let mut words = raw
        .chunks_exact(4)
        .map(|b| u32::from_le_bytes(b.try_into().unwrap()));
    let mut count = 0;
    while let Some(op) = words.next() {
        let mut case = [0; 32];
        case[0] = op;
        for v in &mut case[1..] {
            *v = words.next().unwrap();
        }
        let status = words.next().unwrap();
        let events = words.next().unwrap();
        let trace: Vec<_> = (0..events * 8).map(|_| words.next().unwrap()).collect();
        STATE.with_borrow_mut(|s| *s = State::new(case));
        let result = std::panic::catch_unwind(|| unsafe {
            match op {
                0 => production::wait::<Access>(),
                1 => production::ulp_set::<Access>(case[1], case[2]),
                2 => production::ulp_track::<Access>(case[1]),
                3 => production::pll_track::<Access>(case[1]),
                4 => production::power_track::<Access>(case[1], case[2], case[3]),
                5 => production::offset::<Access>(),
                #[cfg(esp32c3)]
                6 => production::rfcal::<Access>(case[1], case[2]),
                #[cfg(esp32s3)]
                7 => production::radio_power::<Access>(0, case[1], case[2]),
                #[cfg(esp32s3)]
                8 => production::radio_power::<Access>(1, case[1], case[2]),
                _ => panic!("unknown operation"),
            }
        });
        let actual = match result {
            Ok(()) => 0,
            Err(e) => {
                if e.is::<BoundaryStop>() {
                    1
                } else {
                    std::panic::resume_unwind(e)
                }
            }
        };
        assert_eq!(actual, status, "case {count} {case:?}");
        STATE.with_borrow(|s| {
            if s.trace != trace {
                let at = s
                    .trace
                    .iter()
                    .zip(&trace)
                    .position(|(a, b)| a != b)
                    .unwrap_or(s.trace.len().min(trace.len()))
                    / 8
                    * 8;
                panic!(
                    "case {count} {case:?}; event {}: actual {:?} expected {:?}; lengths {}/{}",
                    at / 8,
                    &s.trace[at.min(s.trace.len())..(at + 8).min(s.trace.len())],
                    &trace[at.min(trace.len())..(at + 8).min(trace.len())],
                    s.trace.len(),
                    trace.len()
                );
            }
        });
        count += 1;
    }
    assert_eq!(
        count,
        std::env::var("PHY_TRACK_CASE_COUNT")
            .unwrap()
            .parse::<usize>()
            .unwrap()
    );
    println!("{count} original instruction cases passed");
}
