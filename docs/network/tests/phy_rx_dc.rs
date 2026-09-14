#![allow(dead_code)]
use std::{cell::RefCell, collections::BTreeMap, fs};
#[path = "../../../esp-wifi-hal/src/phy_rx_dc.rs"]
mod production;
use production::Access;
const DATA: usize = 0x300000;
const STATUS: usize = 0x310000;
const OUT: usize = 0x320000;
const PARAM: usize = 0x230000;
const TABLE: usize = 0x220000;
const LOCAL: usize = 0x500000;
const S3: bool = cfg!(esp32s3);
const CELLS: usize = if S3 { 14 } else { 42 };
const GATE: usize = if S3 { 736 } else { 842 };
const SELECTOR: usize = if S3 { 730 } else { 844 };
const WORDS: usize = 133;
struct State {
    c: [u32; WORDS],
    mem: BTreeMap<usize, u8>,
    trace: Vec<u32>,
    calls: usize,
}
impl State {
    fn put(&mut self, a: usize, w: usize, v: u32) {
        for i in 0..w {
            self.mem.insert(a + i, (v >> (8 * i)) as u8);
        }
    }
    fn get(&self, a: usize, w: usize) -> u32 {
        if (0x70000000..0x71000000).contains(&a) {
            assert_eq!(w, 4);
            assert_eq!(a % 4, 0);
            return a as u32 + 0x1000000;
        }
        (0..w).fold(0, |v, i| {
            v | ((*self
                .mem
                .get(&(a + i))
                .unwrap_or_else(|| panic!("Uninitialized {a:x}/{w}")) as u32)
                << (8 * i))
        })
    }
    fn event(&mut self, kind: u32, args: &[u32]) {
        assert!(args.len() < 8);
        self.trace.push(kind);
        self.trace.extend(args);
        self.trace.extend(std::iter::repeat_n(0, 7 - args.len()));
    }
    fn write(&mut self, a: usize, w: usize, v: u32) {
        let v = if w == 4 { v } else { v & ((1 << (w * 8)) - 1) };
        self.event(2, &[a as u32, w as u32, v]);
        self.put(a, w, v);
    }
    fn status(&self) -> usize {
        if self.c[5] != 0 { DATA } else { STATUS }
    }
    fn callback(&mut self, target: usize, args: &[u32], kind: u32) -> i32 {
        let index = self.calls;
        self.calls += 1;
        let offset = if kind == 0 {
            if S3 { 0xf8 } else { 0x10c }
        } else if S3 {
            0xec
        } else {
            0x100
        };
        assert!((0x71000000..0x72000000).contains(&target));
        assert_eq!((target - 0x71000000) % 0x1000, offset);
        let mut call = vec![target as u32];
        call.extend(args);
        self.event(3, &call);
        let result = if kind == 0 {
            assert!(index < 8);
            assert_eq!(args[0], 1);
            assert_eq!(args[1], if S3 { self.c[1] & 65535 } else { self.c[1] });
            for i in 0..3 {
                self.write(args[2] as usize + 4 * i, 4, self.c[9 + index * 3 + i]);
            }
            self.write(PARAM + GATE, 2, self.c[33 + index * 2]);
            self.write(PARAM + SELECTOR, 1, self.c[34 + index * 2]);
            0
        } else {
            let result = if self.c[6] == 0 {
                (args[0] as i32).abs()
            } else {
                self.c[7] as i32
            };
            if self.c[8] != 0 {
                self.write(
                    self.status() + (index * 7 + 5) % CELLS,
                    1,
                    (index % 3) as u32,
                );
                let a = DATA + ((index * 11 + 2) % CELLS) * 4;
                self.write(a, 4, self.get(a, 4) ^ (0x12345678 + index as u32));
            }
            result
        };
        if self.c[3] != 0 {
            self.write(TABLE, 4, 0x70000000 + self.calls as u32 * 0x1000);
        }
        self.event(4, &[result as u32]);
        result
    }
    fn new(c: [u32; WORDS]) -> Self {
        let mut s = Self {
            c,
            mem: BTreeMap::new(),
            trace: vec![],
            calls: 0,
        };
        for (base, len) in [(PARAM, 1024), (DATA, 168), (STATUS, 42), (OUT, 12)] {
            for i in 0..len {
                s.put(base + i, 1, if base == OUT { 0xa5 } else { 0 });
            }
        }
        s.put(TABLE, 4, 0x70000000);
        if c[0] == 1 {
            for i in 0..CELLS {
                s.put(DATA + i * 4, 4, c[49 + i]);
            }
            for i in 0..CELLS {
                s.put(s.status() + i, 1, c[91 + i]);
            }
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
    unsafe fn read(a: usize, w: usize) -> u32 {
        state(|s| {
            let v = s.get(a, w);
            s.event(1, &[a as u32, w as u32, v]);
            v
        })
    }
    unsafe fn write(a: usize, w: usize, v: u32) {
        state(|s| s.write(a, w, v));
    }
    unsafe fn table_global() -> usize {
        TABLE
    }
    unsafe fn parameter_address() -> usize {
        PARAM
    }
    unsafe fn local(_: *mut u32) -> usize {
        LOCAL
    }
    unsafe fn estimate(target: usize, samples: u32, output: usize) {
        state(|s| {
            s.callback(target, &[1, samples, output as u32], 0);
        });
    }
    unsafe fn difference(target: usize, value: i32) -> i32 {
        state(|s| s.callback(target, &[value as u32], 1))
    }
}
fn main() {
    let bytes = fs::read(std::env::args().nth(1).unwrap()).unwrap();
    assert_eq!(bytes.len() % 4, 0);
    let words: Vec<u32> = bytes
        .chunks_exact(4)
        .map(|v| u32::from_le_bytes(v.try_into().unwrap()))
        .collect();
    let (mut at, mut count) = (0, 0);
    while at < words.len() {
        let c: [u32; WORDS] = words[at..at + WORDS].try_into().unwrap();
        let n = words[at + WORDS] as usize;
        let expected = &words[at + WORDS + 1..at + WORDS + 1 + n];
        STATE.with(|s| *s.borrow_mut() = Some(State::new(c)));
        unsafe {
            match c[0] {
                0 => production::minimum::<Mock>(
                    c[1],
                    c[2],
                    if c[4] != 0 { PARAM + (GATE & !3) } else { OUT },
                ),
                1 => production::sort::<Mock>(DATA, if c[5] != 0 { DATA } else { STATUS }),
                _ => panic!("Unknown operation"),
            }
        }
        state(|s| {
            if s.trace != expected {
                let i = s
                    .trace
                    .iter()
                    .zip(expected)
                    .position(|(a, b)| a != b)
                    .unwrap_or(s.trace.len().min(expected.len()))
                    / 8;
                panic!(
                    "Case {count}, event {i}, source {:?}, original {:?}, lengths {}/{}",
                    s.trace.chunks(8).nth(i),
                    expected.chunks(8).nth(i),
                    s.trace.len(),
                    expected.len()
                );
            }
        });
        at += WORDS + 1 + n;
        count += 1;
    }
    println!("{count} ordered RX-DC production cases passed");
}
