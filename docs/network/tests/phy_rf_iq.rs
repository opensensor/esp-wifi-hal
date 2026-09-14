#![allow(dead_code)]
use std::{cell::RefCell, collections::BTreeMap, fs};
#[path = "../../../esp-wifi-hal/src/phy_rf_iq.rs"]
mod production;
use production::Access;
const MMIO: usize = 0x6000607c;
struct State {
    c: [u32; 20],
    mem: BTreeMap<usize, u8>,
    trace: Vec<u32>,
    generation: u32,
    mutations: u32,
    sample: usize,
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
        self.mutations += 1;
        if self.c[7] != 0 {
            self.generation += 1;
            self.put(0x220000, 4, 0x70000000 + self.generation * 0x1000);
        }
        if self.c[6] != 0 {
            self.put(
                MMIO,
                4,
                self.get(MMIO, 4) ^ self.c[6].wrapping_add(self.mutations.wrapping_mul(self.c[18])),
            );
        }
    }
    fn new(c: [u32; 20]) -> Self {
        let mut s = Self {
            c,
            mem: BTreeMap::new(),
            trace: vec![],
            generation: 0,
            mutations: 0,
            sample: 0,
        };
        s.put(MMIO, 4, c[5]);
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
    unsafe fn start(f: u32, g: u32) {
        state(|s| {
            s.event(3, &[1, f, g, 0, 0, 0]);
            s.mutate();
        })
    }
    unsafe fn stop() {
        state(|s| {
            s.event(5, &[1]);
            s.mutate();
        })
    }
    unsafe fn correct(mode: u32, a: usize, b: usize, l: u32) {
        state(|s| {
            assert!(s.sample < 4);
            let m = s.c[10 + s.sample * 2];
            let p = s.c[11 + s.sample * 2];
            s.sample += 1;
            s.event(4, &[mode, a as u32, b as u32, l, m, p]);
            s.put(a, 1, m);
            s.put(b, 1, p);
            s.mutate();
        })
    }
    unsafe fn log(i: u32, m: i32, p: i32) {
        state(|s| {
            s.event(6, &[i, m as u32, p as u32]);
            s.mutate();
        })
    }
    unsafe fn table_global() -> usize {
        0x220000
    }
    unsafe fn difference(t: usize, v: i32) -> i32 {
        state(|s| {
            assert_eq!(
                (t - 0x71000000) % 0x1000,
                if cfg!(esp32s3) { 0xec } else { 0x100 }
            );
            let result = match s.c[9] {
                0 => v.abs(),
                1 => -1,
                2 => 256,
                3 => i32::MIN,
                4 => 2,
                _ => panic!("Unknown callback"),
            };
            s.event(9, &[t as u32, v as u32, result as u32]);
            s.mutate();
            result
        })
    }
    unsafe fn local(k: u32, _: *mut u8) -> usize {
        assert!(k <= 1);
        0x500000 + k as usize * 0x100
    }
    unsafe fn sample(m: u32, f: u32, g: u32, p: usize, l: u32) {
        state(|s| s.event(7, &[m, f, g, p as u32, l]));
        unsafe { production::sample::<Mock>(m, f, g, p, l) };
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
        let c: [u32; 20] = words[at..at + 20].try_into().unwrap();
        let n = words[at + 20] as usize;
        let expected = &words[at + 21..at + 21 + n];
        STATE.with(|s| *s.borrow_mut() = Some(State::new(c)));
        unsafe {
            match c[0] {
                0 => production::sample::<Mock>(
                    c[1],
                    c[2],
                    c[3],
                    [0x300000, MMIO, 0x220000][c[8] as usize],
                    c[4],
                ),
                1 => {
                    let v = production::collect::<Mock>(c[2], c[3], c[4]);
                    state(|s| s.event(10, &[v]));
                }
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
        at += 21 + n;
        count += 1;
    }
    println!("{count} ordered RF-IQ cases passed");
}
