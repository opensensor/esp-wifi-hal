#![allow(dead_code)]
use std::{cell::RefCell, collections::BTreeMap, fs};
#[path = "../../../esp-wifi-hal/src/phy_rx_controls.rs"]
mod production;
use production::Access;
const MMIO: [usize; 7] = [
    0x6001c068, 0x6001c05c, 0x6001c02c, 0x60006140, 0x60006144, 0x60006174, 0x6001c08c,
];
struct State {
    c: [u32; 12],
    mem: BTreeMap<usize, u8>,
    trace: Vec<u32>,
    polls: u32,
    samples: u32,
    generation: u32,
}
impl State {
    fn put(&mut self, a: usize, w: usize, v: u32) {
        for i in 0..w {
            self.mem.insert(a + i, (v >> (i * 8)) as u8);
        }
    }
    fn get(&self, a: usize, w: usize) -> u32 {
        if (0x70000000..0x70400000).contains(&a) {
            assert_eq!(w, 4);
            assert_eq!(a % 4, 0);
            return a as u32 + 0x1000000;
        }
        (0..w).fold(0, |v, i| {
            v | ((*self
                .mem
                .get(&(a + i))
                .unwrap_or_else(|| panic!("Uninitialized {a:x}/{w}")) as u32)
                << (i * 8))
        })
    }
    fn event(&mut self, k: u32, args: &[u32]) {
        assert!(args.len() <= 5);
        self.trace.push(k);
        self.trace.extend(args);
        self.trace.extend(std::iter::repeat_n(0, 5 - args.len()));
    }
    fn observed(a: usize) -> bool {
        (0x200000..0x200000 + if cfg!(esp32s3) { 740 } else { 848 }).contains(&a)
            || a == 0x220000
            || MMIO.contains(&a)
            || (0x70000000..0x70400000).contains(&a)
    }
    fn mutate(&mut self) {
        if self.c[7] != 0 {
            self.generation += 1;
            self.put(0x220000, 4, 0x70000000 + self.generation * 0x1000);
        }
        if self.c[8] != 0 {
            self.put(0x200000 + production::COUNT, 2, self.c[8]);
        }
        if self.c[10] != 0 {
            for a in MMIO {
                self.put(a, 4, self.get(a, 4) ^ self.c[10]);
            }
        }
    }
    fn new(c: [u32; 12]) -> Self {
        let mut s = Self {
            c,
            mem: BTreeMap::new(),
            trace: vec![],
            polls: 0,
            samples: 0,
            generation: 0,
        };
        for i in 0..if cfg!(esp32s3) { 740 } else { 848 } {
            s.put(0x200000 + i, 1, c[3].wrapping_add(i as u32 * 17));
        }
        s.put(0x220000, 4, 0x70000000);
        for a in MMIO {
            s.put(a, 4, c[3] ^ a as u32);
        }
        s
    }
}
thread_local! {static STATE:RefCell<Option<State>>=const{RefCell::new(None)};}
fn state<T>(f: impl FnOnce(&mut State) -> T) -> T {
    STATE.with(|s| f(s.borrow_mut().as_mut().unwrap()))
}
struct Mock;
impl Access for Mock {
    unsafe fn parameter() -> usize {
        0x200000
    }
    unsafe fn table_global() -> usize {
        0x220000
    }
    unsafe fn local(_: *mut u16) -> usize {
        0x500000
    }
    unsafe fn read(a: usize, w: usize) -> u32 {
        state(|s| {
            if a == 0x60006174 {
                let v = (s.c[3] & !0x10000) | if s.polls >= s.c[4] { 0x10000 } else { 0 };
                s.polls += 1;
                s.put(a, 4, v);
            }
            if a == 0x6001c08c {
                let level = s.c[5].wrapping_add(s.samples.wrapping_mul(s.c[6])) & 127;
                s.samples += 1;
                s.put(a, 4, (s.c[3] & !0x7f000) | (level << 12));
            }
            let v = s.get(a, w);
            if State::observed(a) {
                s.event(1, &[a as u32, w as u32, v]);
                if MMIO.contains(&a) && s.c[9] != 0 {
                    s.put(a, w, v ^ s.c[9]);
                }
            }
            v
        })
    }
    unsafe fn write(a: usize, w: usize, v: u32) {
        state(|s| {
            let v = if w == 4 { v } else { v & ((1 << (8 * w)) - 1) };
            if State::observed(a) {
                s.event(2, &[a as u32, w as u32, v]);
            }
            s.put(a, w, v);
        })
    }
    unsafe fn delay(us: u32) {
        state(|s| {
            s.event(5, &[us]);
            s.mutate();
        })
    }
    unsafe fn callback(target: usize, argument: Option<usize>) {
        state(|s| {
            let offset = (target - 0x71000000) % 0x1000;
            let slots = if cfg!(esp32s3) {
                [0x1b0, 0x1c0, 0x1cc, 0x1b4]
            } else {
                [0x1d4, 0x1e4, 0x1f0, 0x1d8]
            };
            assert!(slots.contains(&offset));
            assert_eq!(argument.is_some(), slots[1..3].contains(&offset));
            if offset == slots[2] {
                let a = argument.unwrap();
                s.event(7, &[s.get(a, 4), s.get(a + 4, 4)]);
            }
            let mut row = vec![target as u32, argument.is_some() as u32];
            if let Some(a) = argument {
                row.push(a as u32);
            }
            s.event(6, &row);
            s.mutate();
        })
    }
    unsafe fn trigger() {
        state(|s| s.event(3, &[]));
        unsafe {
            production::trigger::<Mock>();
        }
        state(|s| s.event(4, &[]));
    }
}
fn main() {
    let raw = fs::read(std::env::args().nth(1).unwrap()).unwrap();
    assert_eq!(raw.len() % 4, 0);
    let words: Vec<u32> = raw
        .chunks_exact(4)
        .map(|v| u32::from_le_bytes(v.try_into().unwrap()))
        .collect();
    let mut at = 0;
    let mut count = 0;
    while at < words.len() {
        let c: [u32; 12] = words[at..at + 12].try_into().unwrap();
        let n = words[at + 12] as usize;
        let expected = &words[at + 13..at + 13 + n];
        STATE.with(|s| *s.borrow_mut() = Some(State::new(c)));
        unsafe {
            match c[0] {
                0 => production::reset::<Mock>(c[1]),
                1 => production::trigger::<Mock>(),
                2 => production::estimate::<Mock>(c[1], c[2]),
                3 => production::check::<Mock>(),
                4 => production::reset::<Mock>(1),
                _ => panic!("Unknown case"),
            }
        }
        state(|s| {
            if s.trace != expected {
                let difference = s
                    .trace
                    .iter()
                    .zip(expected)
                    .position(|(a, b)| a != b)
                    .unwrap_or(s.trace.len().min(expected.len()));
                panic!(
                    "Case {count} {c:?}: event {}, source {:?}, original {:?}, lengths {}/{}",
                    difference / 6,
                    s.trace.chunks(6).nth(difference / 6),
                    expected.chunks(6).nth(difference / 6),
                    s.trace.len(),
                    expected.len()
                );
            }
        });
        at += 13 + n;
        count += 1;
    }
    println!("{} ordered RX-control cases passed", count);
}
