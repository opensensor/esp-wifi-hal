#![allow(dead_code)]
use std::{cell::RefCell, collections::BTreeMap, fs};
#[path = "../../../esp-wifi-hal/src/phy_rx_iq.rs"]
mod production;
use production::Access;
const MMIO: [usize; 5] = [0x60006148, 0x60006154, 0x60006150, 0x6000614c, 0x60006164];
struct State {
    c: [u32; 12],
    mem: BTreeMap<usize, u8>,
    trace: Vec<u32>,
    generation: u32,
    mutations: u32,
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
        assert!(args.len() < 8);
        self.trace.push(k);
        self.trace.extend(args);
        self.trace.extend(std::iter::repeat_n(0, 7 - args.len()));
    }
    fn mutate(&mut self) {
        if self.c[9] != 0 {
            self.generation += 1;
            self.put(0x220000, 4, 0x70000000 + self.generation * 0x1000);
        }
        self.mutations += 1;
        if self.c[8] != 0 {
            for (i, a) in MMIO.into_iter().enumerate() {
                self.put(
                    a,
                    4,
                    self.get(a, 4)
                        ^ self.c[8]
                            .wrapping_add(self.mutations.wrapping_mul(self.c[11]))
                            .wrapping_add(i as u32 * 0x1020304),
                );
            }
        }
    }
    fn new(c: [u32; 12]) -> Self {
        let mut s = Self {
            c,
            mem: BTreeMap::new(),
            trace: vec![],
            generation: 0,
            mutations: 0,
        };
        for (a, v) in MMIO.into_iter().zip(c[3..8].iter()) {
            s.put(a, 4, *v);
        }
        s.put(0x220000, 4, 0x70000000);
        s.put(0x300000, 4, 0xa5a5a5a5);
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
        state(|s| {
            let v = if w == 4 { v } else { v & ((1 << (w * 8)) - 1) };
            s.event(2, &[a as u32, w as u32, v]);
            s.put(a, w, v)
        })
    }
    unsafe fn divide(n: i64, d: i64) -> i64 {
        state(|s| {
            let q = n.checked_div(d).expect("Unmodeled division");
            s.event(
                4,
                &[
                    n as u32,
                    (n >> 32) as u32,
                    d as u32,
                    (d >> 32) as u32,
                    q as u32,
                    (q >> 32) as u32,
                ],
            );
            q
        })
    }
    unsafe fn log(sample: i32, m: i32, p: i32) {
        state(|s| {
            s.event(6, &[sample as u32, m as u32, p as u32]);
            s.mutate();
        })
    }
    unsafe fn set(c: i32, m: u32) -> u32 {
        state(|s| {
            assert!(m <= 1);
            let c = if cfg!(esp32s3) { c as i8 as i32 } else { c };
            let v = if m == 1 {
                (c / 2).clamp(-15, 15) * 2
            } else {
                c.clamp(-31, 31)
            };
            let result = if cfg!(esp32s3) {
                v as u8 as u32
            } else {
                v as u32
            };
            s.event(3, &[c as u32, m, result]);
            s.mutate();
            result
        })
    }
    unsafe fn table_global() -> usize {
        0x220000
    }
    unsafe fn local(_: *mut u8) -> usize {
        0x500000
    }
    unsafe fn callback(target: usize, samples: Option<u32>) {
        state(|s| {
            let slots = if cfg!(esp32s3) {
                [0xf0, 0xf4]
            } else {
                [0x104, 0x108]
            };
            let offset = (target - 0x71000000) % 0x1000;
            assert!(slots.contains(&offset));
            assert_eq!(samples.is_some(), offset == slots[0]);
            let mut args = vec![target as u32, if samples.is_some() { 2 } else { 0 }];
            if let Some(n) = samples {
                assert!(n <= 65535);
                args.extend([1, n]);
            }
            s.event(5, &args);
            s.mutate();
        })
    }
    unsafe fn measure(m: u32, p: usize, l: u32) {
        state(|s| s.event(7, &[m, p as u32, l]));
        unsafe { production::mismatch::<Mock>(m, p, l) };
        state(|s| s.event(8, &[]));
    }
}
fn main() {
    let raw = fs::read(std::env::args().nth(1).unwrap()).unwrap();
    assert_eq!(raw.len() % 4, 0);
    let words: Vec<u32> = raw
        .chunks_exact(4)
        .map(|v| u32::from_le_bytes(v.try_into().unwrap()))
        .collect();
    let (mut at, mut count) = (0, 0);
    while at < words.len() {
        let c: [u32; 12] = words[at..at + 12].try_into().unwrap();
        let n = words[at + 12] as usize;
        let expected = &words[at + 13..at + 13 + n];
        STATE.with(|s| *s.borrow_mut() = Some(State::new(c)));
        let a = if c[10] < 2 {
            0x300000
        } else if c[10] == 2 {
            0x60006164
        } else {
            0x220000
        };
        let b = a + if c[10] == 1 { 0 } else { 1 };
        unsafe {
            match c[0] {
                0 => production::mismatch::<Mock>(c[1], a, c[2]),
                1 => production::correct::<Mock>(c[1], a, b, c[2]),
                _ => panic!("Unknown case"),
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
                    "Case {count} {c:?}: event {i}, source {:?}, original {:?}, lengths {}/{}",
                    s.trace.chunks(8).nth(i),
                    expected.chunks(8).nth(i),
                    s.trace.len(),
                    expected.len()
                );
            }
        });
        at += 13 + n;
        count += 1;
    }
    println!("{count} ordered RX-IQ cases passed");
}
