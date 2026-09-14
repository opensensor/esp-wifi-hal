#![allow(dead_code)]
use std::{cell::RefCell, collections::BTreeMap, fs};
#[path = "../../../esp-wifi-hal/src/phy_dc_search.rs"]
mod production;
use production::Access;
const S3: bool = cfg!(esp32s3);
const TABLE: usize = 0x220000;
const OUT: usize = 0x310000;
const WORDS: usize = 121;
struct State {
    c: [u32; WORDS],
    mem: BTreeMap<usize, u8>,
    trace: Vec<u32>,
    calls: usize,
    reads: usize,
    estimates: usize,
    absolute: usize,
    generation: usize,
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
        assert!(args.len() < 12);
        self.trace.push(kind);
        self.trace.extend(args);
        self.trace.extend(std::iter::repeat_n(0, 11 - args.len()));
    }
    fn observed(a: usize) -> bool {
        (0x300000..0x300020).contains(&a)
            || (OUT..OUT + 16).contains(&a)
            || (0x320000..0x320004).contains(&a)
    }
    fn write(&mut self, a: usize, w: usize, v: u32) {
        let v = if w == 4 { v } else { v & ((1 << (w * 8)) - 1) };
        if Self::observed(a) {
            self.event(2, &[a as u32, w as u32, v]);
        }
        self.put(a, w, v);
    }
    fn coeff(&self) -> usize {
        if self.c[8] == 1 { OUT + 2 } else { 0x300002 }
    }
    fn status(&self) -> usize {
        match self.c[8] {
            2 => self.coeff() + 1,
            3 => OUT + 8,
            _ => 0x320000,
        }
    }
    fn samples(&self) -> u32 {
        if S3 { self.c[1] & 65535 } else { self.c[1] }
    }
    fn new(c: [u32; WORDS]) -> Self {
        let mut s = Self {
            c,
            mem: BTreeMap::new(),
            trace: vec![],
            calls: 0,
            reads: 0,
            estimates: 0,
            absolute: 0,
            generation: 0,
        };
        for (a, n) in [(0x300000, 32), (OUT, 16), (0x320000, 4)] {
            for i in 0..n {
                s.put(a + i, 1, 0xa5);
            }
        }
        for i in 0..4 {
            s.put(s.coeff() + i * 2, 2, c[14 + i]);
        }
        s.put(TABLE, 4, 0x70000000);
        s
    }
    fn call(&mut self, kind: u32, target: usize, args: &[u32]) -> i32 {
        if kind < 5 {
            let slot = match kind {
                0 => {
                    if S3 {
                        0x1ac
                    } else {
                        0x1d0
                    }
                }
                1 => {
                    if S3 {
                        0x1a8
                    } else {
                        0x1cc
                    }
                }
                2 => {
                    if S3 {
                        0xf8
                    } else {
                        0x10c
                    }
                }
                3 => {
                    if S3 {
                        0xec
                    } else {
                        0x100
                    }
                }
                4 => 40,
                _ => unreachable!(),
            };
            assert_eq!(target, 0x71000000 + self.generation * 0x1000 + slot);
        }
        let mut call = vec![kind, target as u32];
        call.extend(args);
        if kind == 6 {
            call[3] = 0;
        }
        self.event(3, &call);
        let result = match kind {
            0 => {
                let v = self.c[10 + self.reads];
                self.reads += 1;
                v
            }
            2 | 6 => {
                assert!(self.estimates < 32);
                assert_eq!(
                    &args[..2],
                    if kind == 2 {
                        [1, self.samples()]
                    } else {
                        [self.samples(), 1]
                    }
                );
                let n = self.estimates % (self.c[12] as usize);
                for i in 0..3 {
                    self.write(args[2] as usize + i * 4, 4, self.c[18 + n * 3 + i]);
                }
                self.estimates += 1;
                0
            }
            3 => {
                let v = if self.c[13] != 0 {
                    self.c[114 + self.absolute % (self.c[13] as usize)]
                } else {
                    (args[0] as i32).wrapping_abs() as u32
                };
                self.absolute += 1;
                v
            }
            4 => (args[0] as i32).clamp(args[2] as i32, args[1] as i32) as u32,
            _ => 0,
        };
        if self.c[9] != 0 && [1, 3, 4].contains(&kind) {
            let a = [self.coeff(), self.coeff() + 2, OUT, OUT + 4, self.status()][self.calls % 5];
            let w = if [self.coeff(), self.coeff() + 2].contains(&a) {
                2
            } else if a == self.status() {
                1
            } else {
                4
            };
            self.write(a, w, self.get(a, w) ^ (0x1357 + self.calls as u32));
        }
        self.calls += 1;
        if self.c[7] != 0 {
            self.generation += 1;
            self.put(TABLE, 4, 0x70000000 + self.generation as u32 * 0x1000);
        }
        self.event(4, &[result]);
        result as i32
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
            if State::observed(a) {
                s.event(1, &[a as u32, w as u32, v]);
            }
            v
        })
    }
    unsafe fn write(a: usize, w: usize, v: u32) {
        state(|s| s.write(a, w, v));
    }
    unsafe fn table_global() -> usize {
        TABLE
    }
    unsafe fn coarse(i: u32) -> u32 {
        [80, 71, 63, 56, 50, 44][i as usize]
    }
    unsafe fn local(_: *mut u32, tag: usize) -> usize {
        0x500000 + tag * 0x100
    }
    unsafe fn pbus_read(t: usize, b: u32, k: u32) -> u32 {
        state(|s| s.call(0, t, &[b, k])) as u32
    }
    unsafe fn force(t: usize, b: u32, k: u32, v: u32) {
        state(|s| s.call(1, t, &[b, k, v]));
    }
    unsafe fn estimate(t: usize, n: u32, o: usize) {
        state(|s| s.call(2, t, &[1, n, o as u32]));
    }
    unsafe fn difference(t: usize, v: i32) -> i32 {
        state(|s| s.call(3, t, &[v as u32]))
    }
    unsafe fn limit(t: usize, v: i32) -> i32 {
        state(|s| s.call(4, t, &[v as u32, 5, (-5i32) as u32]))
    }
    unsafe fn minimum(n: u32, o: usize) {
        state(|s| s.call(6, 0, &[n, 1, o as u32]));
    }
    unsafe fn delay(v: u32) {
        state(|s| s.call(5, 0, &[v]));
    }
    unsafe fn log(k: u32, a: &[u32]) {
        let mut v = vec![k];
        v.extend(a);
        state(|s| s.call(7, 0, &v));
    }
}
fn main() {
    let bytes = fs::read(std::env::args().nth(1).unwrap()).unwrap();
    assert_eq!(bytes.len() % 4, 0);
    let words: Vec<u32> = bytes
        .chunks_exact(4)
        .map(|b| u32::from_le_bytes(b.try_into().unwrap()))
        .collect();
    let mut offset = 0;
    let mut count = 0;
    while offset < words.len() {
        let c: [u32; WORDS] = words[offset..offset + WORDS].try_into().unwrap();
        offset += WORDS;
        let length = words[offset] as usize;
        offset += 1;
        let expected = &words[offset..offset + length];
        offset += length;
        STATE.with(|s| *s.borrow_mut() = Some(State::new(c)));
        let (coeff, status) = state(|s| (s.coeff(), s.status()));
        unsafe {
            if c[0] == 0 {
                production::general::<Mock>(c[1], coeff, c[2], c[3], c[4]);
            } else {
                production::one_step::<Mock>(c[5], c[6], c[1], coeff, OUT, status);
            }
        }
        state(|s| {
            if s.trace != expected {
                let at = s
                    .trace
                    .chunks(12)
                    .zip(expected.chunks(12))
                    .position(|(a, b)| a != b)
                    .unwrap_or(s.trace.len().min(expected.len()) / 12);
                panic!(
                    "case {count}, event {at}: actual {:?}; expected {:?}; lengths {}/{}",
                    s.trace.get(at * 12..at * 12 + 12),
                    expected.get(at * 12..at * 12 + 12),
                    s.trace.len(),
                    expected.len()
                );
            }
        });
        count += 1;
    }
    println!(
        "{}: {count} production Rust cases passed",
        if S3 { "esp32s3" } else { "esp32c3" }
    );
}
