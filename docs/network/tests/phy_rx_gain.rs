#![allow(dead_code)]
use std::{cell::RefCell, collections::BTreeMap, fs};
#[path = "../../../esp-wifi-hal/src/phy_rx_gain.rs"]
mod production;
const S3: bool = cfg!(esp32s3);
const MMIO: [usize; 7] = [
    0x60006110, 0x6000607c, 0x6001c02c, 0x6001c13c, 0x6001c0d0, 0x60011848, 0x6001c0a4,
];
struct State {
    c: [u32; 32],
    mem: BTreeMap<usize, u8>,
    trace: Vec<u32>,
    generation: u32,
    calls: u32,
    mmreads: u32,
    mmwrites: u32,
}
impl State {
    fn put(&mut self, a: usize, w: usize, v: u32) {
        for i in 0..w {
            self.mem.insert(a + i, (v >> (i * 8)) as u8);
        }
    }
    fn get(&self, a: usize, w: usize) -> u32 {
        (0..w).fold(0, |v, i| {
            let b = self.mem.get(&(a + i)).copied().unwrap_or_else(|| {
                assert!(
                    [(0x340000, 1024), (0x350000, 16), (0x360000, 262144)]
                        .iter()
                        .any(|(b, n)| *b <= a && a + w <= *b + *n),
                    "Uninitialized {a:x}/{w}"
                );
                self.c[9].wrapping_add(((a + i) * 17) as u32) as u8
            });
            v | ((b as u32) << (8 * i))
        })
    }
    fn event(&mut self, k: u32, a: &[u32]) {
        assert!(a.len() <= 15);
        self.trace.push(k);
        self.trace.extend(a);
        self.trace.extend(std::iter::repeat_n(0, 15 - a.len()));
    }
    fn new(c: [u32; 32]) -> Self {
        let mut s = Self {
            c,
            mem: BTreeMap::new(),
            trace: vec![],
            generation: 0,
            calls: 0,
            mmreads: 0,
            mmwrites: 0,
        };
        for i in 0..if S3 { 740 } else { 848 } {
            s.put(0x200000 + i, 1, c[9].wrapping_add(i as u32 * 17));
        }
        for (o, w, v) in [
            (0x120, 4, c[17]),
            (0x1f2, 1, c[18]),
            (0x1f5, 1, c[25]),
            (0x1f6, 1, c[26]),
            (if S3 { 0x2da } else { 0x348 }, 1, c[19]),
            (0x218, 1, c[29]),
            (0xa2, 1, c[30]),
            (if S3 { 0x2da } else { 0x34c }, 1, c[31]),
        ] {
            s.put(0x200000 + o, w, v);
        }
        for i in 0..256 {
            let code = production::CONSTANTS[(if S3 { 25 } else { 32 }) + i % 9] as u32;
            let mut step = production::CONSTANTS[(if S3 { 10 } else { 0 }) + i % 15];
            let mut start = production::CONSTANTS[(if S3 { 58 } else { 16 }) + i % 15];
            match c[21] {
                1 => {
                    step = 1;
                    start = 0;
                }
                2 => {
                    step = 0;
                    start = 0;
                }
                3 => {
                    step = 255;
                    start = 4;
                }
                4 => {
                    step = 20;
                    start = 0;
                }
                _ => {}
            }
            s.put(0x310000 + i, 1, code.wrapping_add(c[23]));
            s.put(0x320000 + i, 1, step.into());
            s.put(0x330000 + i, 1, start.into());
        }
        for i in 0..128 {
            s.put(
                0x300000 + i * 4,
                4,
                c[22].wrapping_add(i as u32 * 0x01010001),
            );
        }
        for a in MMIO {
            s.put(a, 4, c[9] ^ (a as u32).wrapping_mul(0x1021));
        }
        s
    }
    fn change(&mut self) {
        for o in [0x120, 0x150, 0x152, 0xf3, 0x1f5, 0x1f6, 0xd4] {
            let w = if o == 0x120 || o == 0xd4 {
                4
            } else if o == 0x150 || o == 0x152 {
                2
            } else {
                1
            };
            let v = self.get(0x200000 + o, w) ^ self.c[24].wrapping_add(o as u32 * 17);
            self.put(0x200000 + o, w, v);
        }
    }
    fn mutate(&mut self) {
        let mask = 1 << (self.calls % 32);
        if self.c[13] & mask != 0 {
            self.generation += 1;
        }
        if self.c[14] & mask != 0 {
            self.change();
        }
        self.calls += 1;
    }
}
thread_local! {static STATE:RefCell<Option<State>>=const{RefCell::new(None)};}
fn state<R>(f: impl FnOnce(&mut State) -> R) -> R {
    STATE.with(|s| f(s.borrow_mut().as_mut().unwrap()))
}
struct Mock;
impl production::Access for Mock {
    unsafe fn param() -> usize {
        0x200000
    }
    unsafe fn read(a: usize, w: usize) -> u32 {
        state(|s| {
            let mut v = s.get(a, w);
            if MMIO.contains(&a) {
                assert_eq!(w, 4);
                v ^= s.c[11].wrapping_mul(s.mmreads);
                s.event(7, &[a as u32, v]);
                if s.c[10] & (1 << (s.mmreads % 32)) != 0 {
                    s.change();
                }
                s.mmreads += 1;
            } else {
                s.event(1, &[a as u32, w as u32, v]);
            }
            v
        })
    }
    unsafe fn write(a: usize, w: usize, v: u32) {
        state(|s| {
            let v = if w == 4 { v } else { v & ((1 << (w * 8)) - 1) };
            if MMIO.contains(&a) {
                assert_eq!(w, 4);
                s.event(8, &[a as u32, v]);
                s.put(a, w, v);
                if s.c[12] & (1 << (s.mmwrites % 32)) != 0 {
                    s.change();
                }
                s.mmwrites += 1;
            } else {
                s.event(2, &[a as u32, w as u32, v]);
                s.put(a, w, v);
            }
        });
    }
    unsafe fn table() -> usize {
        state(|s| {
            s.event(4, &[s.generation]);
            0x70000000 + s.generation as usize * 0x1000
        })
    }
    unsafe fn slot(t: usize, o: usize) -> usize {
        state(|s| {
            let g = (t - 0x70000000) / 0x1000;
            assert!(g <= s.generation as usize);
            s.event(5, &[o as u32, g as u32]);
            0x71000000 + g * 0x1000 + o
        })
    }
    unsafe fn call(t: usize, a: &[u32]) -> u32 {
        state(|s| {
            let v = if a.len() == 2 {
                s.c[15].wrapping_add(s.calls.wrapping_mul(s.c[16]))
            } else {
                0
            };
            let mut args = vec![t as u32];
            args.extend(a);
            args.push(v);
            s.event(6, &args);
            s.mutate();
            v
        })
    }
    unsafe fn external(k: u32, a: &[usize]) {
        state(|s| {
            let mut args = vec![k];
            args.extend(a.iter().map(|v| *v as u32));
            s.event(10, &args);
            s.mutate();
        });
    }
    unsafe fn log(k: u32, a: &[u32]) {
        state(|s| {
            let mut args = vec![k];
            args.extend(a);
            s.event(11, &args);
            s.mutate();
        });
    }
    unsafe fn local(_: *mut u32, tag: usize, size: usize) -> usize {
        assert_eq!((tag, size), (0, 512));
        0x500000
    }
    unsafe fn copy(d: usize, o: usize, n: usize) {
        state(|s| {
            for i in 0..n {
                s.put(d + i, 1, production::CONSTANTS[o + i].into());
            }
        });
    }
    unsafe fn child(k: u32, a: &[usize]) -> u32 {
        let (execute, value) = state(|s| {
            let mut args = vec![k];
            args.extend(a.iter().enumerate().map(|(i, v)| {
                if k == 2 && [1, 3, 4].contains(&i) {
                    0
                } else {
                    *v as u32
                }
            }));
            s.event(9, &args);
            let execute = s.c[20] & (1 << k) != 0;
            let v = if k == 0 { s.c[27] } else { 0 };
            if !execute {
                s.mutate();
            }
            (execute, v)
        });
        if !execute {
            return value;
        }
        unsafe {
            match k {
                0 => return production::generate::<Mock>(a),
                1 => production::write_memory::<Mock>(a),
                2 => production::set_param::<Mock>(a),
                _ => panic!(),
            }
        }
        0
    }
}
unsafe fn invoke(c: [u32; 32]) -> u32 {
    unsafe {
        match c[0] {
            0 => {
                return production::generate::<Mock>(&[
                    0x300000,
                    c[2] as usize,
                    0x310000,
                    0x320000,
                    0x330000,
                    c[6] as usize,
                    c[7] as usize,
                ]);
            }
            1 => production::write_memory::<Mock>(&[
                c[1] as usize,
                c[2] as usize,
                0x310000,
                0x340000,
                0x350000,
                0x360000,
                c[7] as usize,
                0x300000,
            ]),
            2 => production::set_param::<Mock>(&[
                c[1] as usize,
                c[2] as usize,
                0x310000,
                c[4] as usize,
                c[5] as usize,
                c[6] as usize,
            ]),
            3 => production::set_table::<Mock>(c[1], c[2]),
            4 => production::initialize::<Mock>(),
            _ => panic!(),
        }
        0
    }
}
#[test]
fn production_matches_original_instruction_effects() {
    let bytes = fs::read(std::env::var("PHY_RX_GAIN_CASES").unwrap()).unwrap();
    assert_eq!(bytes.len() % 4, 0);
    let words: Vec<_> = bytes
        .chunks_exact(4)
        .map(|b| u32::from_le_bytes(b.try_into().unwrap()))
        .collect();
    let mut offset = 0;
    let mut count = 0;
    while offset < words.len() {
        let c: [u32; 32] = words[offset..offset + 32].try_into().unwrap();
        let expected = words[offset + 32];
        let len = words[offset + 33] as usize;
        offset += 34;
        STATE.with(|s| *s.borrow_mut() = Some(State::new(c)));
        let actual = unsafe { invoke(c) };
        assert_eq!(actual, expected, "case {count} kind {} {c:x?}", c[0]);
        let trace = state(|s| s.trace.clone());
        let want = &words[offset..offset + len];
        if trace != want {
            let i = trace
                .iter()
                .zip(want)
                .position(|(a, b)| a != b)
                .unwrap_or(trace.len().min(want.len()));
            let start = i / 16 * 16;
            panic!(
                "case {count} kind {} {c:x?} trace word {i}: actual {:?}, expected {:?}; lengths {}/{}",
                c[0],
                trace.get(start..(start + 16).min(trace.len())),
                want.get(start..(start + 16).min(want.len())),
                trace.len(),
                want.len()
            );
        }
        offset += len;
        count += 1;
    }
    assert_eq!(
        count,
        std::env::var("PHY_RX_GAIN_CASE_COUNT")
            .unwrap()
            .parse::<usize>()
            .unwrap()
    );
}
