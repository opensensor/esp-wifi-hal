#![allow(dead_code)]
use std::{cell::RefCell, collections::BTreeMap, fs};
#[path = "../../../esp-wifi-hal/src/phy_rx_gain_cal.rs"]
mod production;
use production::Access;
const S3: bool = cfg!(esp32s3);
const WORDS: usize = 59;
struct State {
    c: [u32; WORDS],
    mem: BTreeMap<usize, u8>,
    trace: Vec<u32>,
    calls: usize,
    generation: usize,
    estimates: usize,
    collections: usize,
    searches: usize,
}
impl State {
    fn put(&mut self, a: usize, w: usize, v: u32) {
        for i in 0..w {
            self.mem.insert(a + i, (v >> (i * 8)) as u8);
        }
    }
    fn get(&self, a: usize, w: usize) -> u32 {
        assert!(matches!(w, 1 | 2 | 4));
        assert_eq!(a % w, 0, "Unaligned {a:x}/{w}");
        if (0x70000000..0x71000000).contains(&a) {
            assert_eq!(w, 4);
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
    fn canonical(a: usize) -> usize {
        if (0x10f000..0x10f22a).contains(&a) {
            a - 0x10f000 + 0x500000
        } else {
            a
        }
    }
    fn observed(a: usize) -> bool {
        (0x230000..0x230400).contains(&a)
            || (0x300000..0x330100).contains(&a)
            || (0x60000000..0x60020000).contains(&a)
    }
    fn event(&mut self, k: u32, args: &[u32]) {
        assert!(args.len() < 48);
        self.trace.push(k);
        self.trace.extend(args);
        self.trace.extend(std::iter::repeat_n(0, 47 - args.len()));
    }
    fn read(&mut self, a: usize, w: usize) -> u32 {
        let v = self.get(a, w);
        if Self::observed(a) {
            self.event(1, &[Self::canonical(a) as u32, w as u32, v]);
        }
        v
    }
    fn write(&mut self, a: usize, w: usize, v: u32) {
        assert_eq!(a % w, 0);
        let v = if w == 4 { v } else { v & ((1 << (8 * w)) - 1) };
        if Self::observed(a) {
            self.event(2, &[Self::canonical(a) as u32, w as u32, v]);
        }
        self.put(a, w, v);
    }
    fn codes(&self) -> usize {
        if self.c[16] == 1 { 0x310028 } else { 0x300000 }
    }
    fn dc(&self) -> usize {
        if self.c[16] == 2 { 0x310028 } else { 0x320000 }
    }
    fn channels(&self) -> usize {
        if self.c[16] == 3 { 0x310020 } else { 0x330000 }
    }
    fn new(c: [u32; WORDS]) -> Self {
        let mut s = Self {
            c,
            mem: BTreeMap::new(),
            trace: vec![],
            calls: 0,
            generation: 0,
            estimates: 0,
            collections: 0,
            searches: 0,
        };
        for (a, n) in [
            (0x300000, 256),
            (0x310000, 256),
            (0x320000, 256),
            (0x330000, 256),
            (0x230000, 1024),
        ] {
            for i in 0..n {
                s.put(a + i, 1, (i as u32 * 7 + c[9]) & 255);
            }
        }
        s.put(0x23014c, 2, c[10]);
        s.put(0x220000, 4, 0x70000000);
        for a in [0x6000607c, 0x60006164, 0x60006160, 0x6000615c] {
            s.put(a, 4, c[11] ^ (a as u32 & 255));
        }
        s
    }
    fn call(&mut self, t: usize, k: u32, a: &[usize]) -> u32 {
        if k < 11 {
            let offsets = if S3 {
                [404, 408, 36, 72, 68, 28, 424, 428, 240, 244, 440]
            } else {
                [440, 444, 36, 84, 80, 28, 460, 464, 260, 264, 476]
            };
            assert_eq!(
                t,
                0x71000000 + self.generation * 0x1000 + offsets[k as usize]
            );
        }
        let mut args = vec![k, if k < 11 { t as u32 } else { 0 }];
        for (i, v) in a.iter().enumerate() {
            args.push(if (k == 20 && i == 1) || (k == 21 && i >= 3) || (k == 27) {
                Self::canonical(*v) as u32
            } else {
                *v as u32
            });
        }
        self.event(3, &args);
        let mut result = 0;
        match k {
            0 => result = self.c[12],
            7 => result = 0x12340000 + (self.calls as u32) * 0x171,
            8 => {
                let v = self.c[20 + self.estimates % (self.c[17] as usize)];
                self.estimates += 1;
                self.put(0x60006164, 4, v);
            }
            25 => {
                result = self.c[13].wrapping_add((self.collections as u32) * 0x12345);
                self.collections += 1;
            }
            20 => {
                assert_eq!([a[0], a[2], a[3], a[4]], [4000, 10, 0, 0]);
                let p = a[1];
                self.event(5, &[0x500000, self.get(p, 2), self.get(p + 2, 2)]);
                for i in 0..4 {
                    self.write(p + i * 2, 2, ((self.calls * 31 + i * 53) & 65535) as u32);
                }
                self.event(
                    6,
                    &[
                        0x500000,
                        self.get(p, 2),
                        self.get(p + 2, 2),
                        self.get(p + 4, 2),
                        self.get(p + 6, 2),
                    ],
                );
            }
            21 => {
                assert_eq!(a[2], 2048);
                self.event(5, &[0x500000, self.get(a[3], 2), self.get(a[3] + 2, 2)]);
                let i = self.searches % (self.c[18] as usize);
                let x = self.c[28 + i * 2];
                let y = self.c[29 + i * 2];
                let status = self.c[52 + self.searches % (self.c[19] as usize)];
                self.searches += 1;
                self.write(a[3], 2, x);
                self.write(a[3] + 2, 2, y);
                for i in 0..3 {
                    self.write(
                        a[4] + i * 4,
                        4,
                        0x12340000 + self.searches as u32 + i as u32,
                    );
                }
                self.write(a[5], 1, status);
                self.event(6, &[0x500000, x & 65535, y & 65535, status & 255]);
            }
            27 => {
                let v: Vec<_> = (0..if S3 { 14 } else { 42 })
                    .map(|i| self.get(a[1] + i, 1))
                    .collect();
                self.event(7, &v);
            }
            _ => {}
        }
        if self.c[14] != 0 {
            let (p, w) = [
                (self.codes() + 2, 1),
                (0x31002c, 4),
                (self.dc() + 4, 2),
                (0x23014c, 2),
                (0x6000607c, 4),
            ][self.calls % 5];
            let v = self.get(p, w) ^ (0x1357 + self.calls as u32);
            self.write(p, w, v);
        }
        self.calls += 1;
        if self.c[15] != 0 {
            self.generation += 1;
            self.put(0x220000, 4, 0x70000000 + self.generation as u32 * 0x1000);
        }
        self.event(4, &[result]);
        result
    }
}
thread_local! {static STATE:RefCell<Option<State>>=const{RefCell::new(None)};}
fn state<R>(f: impl FnOnce(&mut State) -> R) -> R {
    STATE.with(|s| f(s.borrow_mut().as_mut().unwrap()))
}
struct Host;
impl Access for Host {
    unsafe fn read(a: usize, w: usize) -> u32 {
        state(|s| s.read(a, w))
    }
    unsafe fn write(a: usize, w: usize, v: u32) {
        state(|s| s.write(a, w, v));
    }
    unsafe fn parameter() -> usize {
        0x230000
    }
    unsafe fn table_global() -> usize {
        0x220000
    }
    unsafe fn local(_: *mut u8, k: u32, _: usize) -> usize {
        0x10f000 + k as usize * 256
    }
    unsafe fn call(t: usize, k: u32, a: &[usize]) -> u32 {
        state(|s| s.call(t, k, a))
    }
}
fn main() {
    let data = fs::read(std::env::args().nth(1).expect("fixture")).unwrap();
    assert_eq!(data.len() % 4, 0);
    let words: Vec<u32> = data
        .chunks_exact(4)
        .map(|c| u32::from_le_bytes(c.try_into().unwrap()))
        .collect();
    let mut at = 0;
    let mut cases = 0;
    while at < words.len() {
        let c: [u32; WORDS] = words[at..at + WORDS].try_into().unwrap();
        at += WORDS;
        let len = words[at] as usize;
        at += 1;
        let expected = &words[at..at + len];
        at += len;
        let s = State::new(c);
        let args = [
            c[1] as usize,
            c[4] as usize,
            c[5] as usize,
            s.codes(),
            0x310000,
            s.dc(),
            s.channels(),
            c[6] as usize,
            c[7] as usize,
            c[8] as usize,
        ];
        STATE.with(|v| *v.borrow_mut() = Some(s));
        unsafe {
            if c[0] == 0 {
                production::iq::<Host>(c[1], c[2], 0x310000, c[3]);
            } else {
                production::dc::<Host>(&args);
            }
        }
        state(|s| {
            if s.trace != expected {
                let i = s
                    .trace
                    .iter()
                    .zip(expected)
                    .position(|(a, b)| a != b)
                    .unwrap_or(s.trace.len().min(expected.len()));
                let row = i / 48;
                panic!(
                    "Case {cases} event {row}: actual {:?}, expected {:?}",
                    s.trace.get(row * 48..(row + 1) * 48),
                    expected.get(row * 48..(row + 1) * 48)
                );
            }
        });
        cases += 1;
    }
    println!("{} production cases matched", cases);
}
