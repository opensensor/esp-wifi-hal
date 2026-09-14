#![allow(dead_code)]
use std::{
    cell::RefCell,
    collections::{BTreeMap, BTreeSet},
    fs,
};
#[path = "../../../esp-wifi-hal/src/phy_hw_freq.rs"]
mod production;
const S3: bool = cfg!(esp32s3);
fn fields() -> Vec<(usize, usize)> {
    let mut f = vec![
        (0xf3, 1),
        (0xde, 2),
        (0xe2, 2),
        (if S3 { 0x2aa } else { 0x326 }, 2),
        (0x120, 4),
    ];
    for i in 0..6 {
        f.push((0x158 + i, 1));
    }
    f
}
fn pointers(c: &[u32; 48]) -> [usize; 8] {
    core::array::from_fn(|i| {
        0x300000
            + match c[28] {
                0 => i * 0x400,
                1 => 0,
                2 => i,
                3 => (i % 2) * 0x400,
                _ => panic!(),
            }
    })
}
fn initial_byte(c: &[u32; 48], a: usize, i: usize) -> u32 {
    (match c[40] {
        0 => c[27].wrapping_add(a as u32 * 29 + i as u32 * 17),
        1 => [1, 99, 3, 0, 0x9a, 1, 0x65, 1][a],
        2 => c[27],
        3 => i as u32,
        _ => panic!(),
    }) & 255
}
fn mmio() -> Vec<usize> {
    let mut v = vec![
        0xc0, 0xc4, 0xc8, 0xcc, 0xd0, 0xd4, 0xd8, 0xdc, 0xe0, 0xe4, 0xe8, 0xec, 0xf0, 0xf4, 0x100,
        0x104, 0x108, 0x10c, 0x110, 0x114, 0x118, 0x11c, 0x120, 0x124, 0x128, 0x12c, 0x148, 0x150,
        0x164, 0x168, 0x170,
    ];
    for a in &mut v {
        *a += 0x6000e000;
    }
    v.push(0x6003509c);
    v
}
fn arity(slot: usize) -> usize {
    match slot {
        0x28 => 3,
        0x20c if S3 => 1,
        0x100 if S3 => 2,
        0x114 if !S3 => 2,
        0x188 if S3 => 3,
        0x1ac if !S3 => 3,
        0x194 if S3 => 5,
        0x1b8 if !S3 => 5,
        0x198 if S3 => 6,
        0x1bc if !S3 => 6,
        _ => panic!("unknown slot {slot:x}"),
    }
}
struct State {
    c: [u32; 48],
    memory: BTreeMap<usize, u8>,
    trace: Vec<u32>,
    bindings: Vec<(usize, usize, usize)>,
    contexts: Vec<u32>,
    generation: u32,
    calls: u32,
    mmreads: u32,
    busyreads: u32,
    chanreads: usize,
    capreads: usize,
}
impl State {
    fn put(&mut self, a: usize, w: usize, v: u32) {
        for i in 0..w {
            self.memory.insert(a + i, (v >> (i * 8)) as u8);
        }
    }
    fn get(&self, a: usize, w: usize) -> u32 {
        (0..w).fold(0, |v, i| {
            v | (u32::from(
                *self
                    .memory
                    .get(&(a + i))
                    .unwrap_or_else(|| panic!("uninitialized {a:x}/{w}")),
            ) << (8 * i))
        })
    }
    fn new(c: [u32; 48]) -> Self {
        let mut s = Self {
            c,
            memory: BTreeMap::new(),
            trace: vec![],
            bindings: vec![],
            contexts: vec![],
            generation: 0,
            calls: 0,
            mmreads: 0,
            busyreads: 0,
            chanreads: 0,
            capreads: 0,
        };
        for (o, w) in fields() {
            s.put(0x200000 + o, w, 0);
        }
        for (o, w, v) in [
            (0x120, 4, c[10]),
            (0xf3, 1, c[11]),
            (0xde, 2, c[12]),
            (0xe2, 2, c[12] >> 16),
            (if S3 { 0x2aa } else { 0x326 }, 2, c[12]),
        ] {
            s.put(0x200000 + o, w, v);
        }
        for (array, a) in pointers(&c).into_iter().enumerate() {
            for i in 0..256 {
                s.put(a + i, 1, initial_byte(&c, array, i));
            }
        }
        for a in mmio() {
            s.put(a, 4, c[25] ^ (a as u32).wrapping_mul(0x1021));
        }
        s
    }
    fn event(&mut self, kind: u32, a: &[u32]) {
        assert!(a.len() <= 11 && self.trace.len() < 12 * 65536);
        self.trace.push(kind);
        self.trace.extend(a);
        self.trace.extend(std::iter::repeat_n(0, 11 - a.len()));
    }
    fn canonical(&self, a: usize) -> u32 {
        if (0x200000..0x200000 + if S3 { 740 } else { 848 }).contains(&a)
            || (0x300000..0x302000).contains(&a)
        {
            return a as u32;
        }
        for &(b, w, t) in self.bindings.iter().rev() {
            if b <= a && a < b + w {
                return (t + a - b) as u32;
            }
        }
        panic!("unknown pointer {a:x}")
    }
    fn bind(&mut self, a: usize, w: usize, t: usize) {
        if (0x100000..0x110000).contains(&a) {
            assert!(
                self.bindings
                    .iter()
                    .all(|&(b, x, y)| b != a || (x == w && y == t)),
                "conflicting binding"
            );
            if !self.bindings.contains(&(a, w, t)) {
                self.bindings.push((a, w, t));
            }
        } else {
            self.canonical(a);
        }
    }
    fn visible(&self, a: usize, w: usize) -> bool {
        (0x200000 <= a && a + w <= 0x200000 + if S3 { 740 } else { 848 })
            || (0x300000 <= a && a + w <= 0x302000)
            || (self.contexts.last().is_some_and(|k| [3, 4, 7].contains(k))
                && self
                    .bindings
                    .iter()
                    .any(|&(b, n, _)| b <= a && a + w <= b + n))
    }
    fn mutate_buffers(&mut self) {
        let addrs: BTreeSet<_> = pointers(&self.c)
            .into_iter()
            .flat_map(|a| (0..256).map(move |i| a + i))
            .collect();
        for a in addrs {
            self.put(
                a,
                1,
                self.get(a, 1) ^ self.c[24].wrapping_add((a - 0x300000) as u32 * 17),
            );
        }
        let b = self.bindings.clone();
        for (a, w, t) in b {
            if t == 0x310000 {
                for i in 0..w {
                    self.put(
                        a + i,
                        1,
                        self.get(a + i, 1) ^ self.c[24].wrapping_add(i as u32 * 17),
                    );
                }
            }
        }
    }
    fn read(&mut self, a: usize, w: usize) -> u32 {
        let mut v = self.get(a, w);
        if a >= 0x60000000 {
            assert!(mmio().contains(&a) && w == 4);
            v ^= self.c[26].wrapping_mul(self.mmreads);
            if a == 0x6000e168 {
                v = (v & 0x7fffffff)
                    | if self.busyreads < 32 {
                        ((self.c[29] >> self.busyreads) & 1) << 31
                    } else {
                        0
                    };
                self.busyreads += 1;
            }
            if a == 0x6000e170 {
                v = self.c[30 + self.chanreads.min(2)];
                self.chanreads += 1;
            }
            self.event(7, &[a as u32, v]);
            if self.c[36] & (1 << (self.mmreads % 32)) != 0 {
                self.mutate_buffers();
            }
            self.mmreads += 1;
        } else if self.visible(a, w) {
            self.event(1, &[self.canonical(a), w as u32, v]);
        }
        v
    }
    fn write(&mut self, a: usize, w: usize, v: u32) {
        let v = if w == 4 { v } else { v & ((1 << (w * 8)) - 1) };
        if a >= 0x60000000 {
            assert!(mmio().contains(&a) && w == 4);
            self.event(8, &[a as u32, v]);
        } else if self.visible(a, w) {
            self.event(2, &[self.canonical(a), w as u32, v]);
        }
        self.put(a, w, v);
    }
    fn mutate(&mut self) {
        assert!(self.calls < 4096);
        let mask = 1 << (self.calls % 32);
        if self.c[21] & mask != 0 {
            self.generation += 1;
        }
        if self.c[22] & mask != 0 {
            for (o, w) in fields() {
                self.put(
                    0x200000 + o,
                    w,
                    self.get(0x200000 + o, w) ^ self.c[24].wrapping_add(o as u32 * 17),
                );
            }
        }
        if self.c[23] & mask != 0 {
            self.mutate_buffers();
        }
        self.calls += 1;
    }
    fn clean_args(&mut self, k: u32, a: &[u32]) -> Vec<u32> {
        let mut clean = a.to_vec();
        if k == 3 {
            self.bind(a[1] as usize, 12, 0x310010);
            clean[1] = self.canonical(a[1] as usize);
            for i in 0..3 {
                self.event(
                    11,
                    &[
                        clean[1] + i * 4,
                        4,
                        self.get(a[1] as usize + i as usize * 4, 4),
                    ],
                );
            }
        } else if k == 4 || k == 7 {
            let count = if S3 { a[7] & 255 } else { a[7] } as usize;
            assert!(count <= 255);
            for (array, index) in [0, 1, 2, 3, 4, 5, 6, 8].into_iter().enumerate() {
                self.bind(a[index] as usize, count.max(1), 0x320000 + array * 0x400);
                clean[index] = self.canonical(a[index] as usize);
                if k == 4 {
                    for i in 0..count {
                        self.event(
                            11,
                            &[
                                clean[index] + i as u32,
                                1,
                                self.get(a[index] as usize + i, 1),
                            ],
                        );
                    }
                }
            }
        }
        clean
    }
    fn callback(&mut self, t: usize, a: &[u32]) -> u32 {
        assert!((0x71000000..0x71400000).contains(&t));
        let slot = (t - 0x71000000) % 0x1000;
        assert_eq!(arity(slot), a.len());
        assert!((t - 0x71000000) / 0x1000 <= self.generation as usize);
        let clear = slot == if S3 { 0x100 } else { 0x114 };
        let mut clean = a.to_vec();
        if clear {
            clean[0] = self.canonical(a[0] as usize);
            assert_eq!(a, [0x200158, 6]);
        }
        let mut args = vec![t as u32];
        args.extend(clean);
        self.event(6, &args);
        let v = if slot == 0x28 {
            if self.c[34] != 0 {
                self.c[35]
            } else {
                (a[0] as i32).clamp(a[2] as i32, a[1] as i32) as u32
            }
        } else if slot == if S3 { 0x194 } else { 0x1b8 } {
            assert_eq!(a, [98, 1, 6, 3, 0]);
            self.c[15]
        } else if slot == if S3 { 0x188 } else { 0x1ac } {
            assert!(a == [98, 1, 11] || a == [99, 1, 0]);
            if a[0] == 98 { self.c[16] } else { self.c[17] }
        } else {
            0
        };
        if clear {
            for i in 0..6 {
                self.put(a[0] as usize + i, 1, self.c[37] >> (8 * (i % 4)));
            }
        }
        self.mutate();
        v
    }
    fn external(&mut self, k: u32, a: &[u32]) -> u32 {
        assert_eq!(a.len(), [1, 1, 4, 0, 4, 0, 3][k as usize]);
        let mut clean = a.to_vec();
        if k == 2 || k == 4 {
            self.bind(a[3] as usize, 3, 0x310000);
            clean[3] = self.canonical(a[3] as usize);
        }
        if k == 6 {
            clean[2] = self.canonical(a[2] as usize);
        }
        let mut args = vec![k];
        args.extend(clean);
        self.event(10, &args);
        if k == 2 || k == 4 {
            let pattern = self.c[20].wrapping_add(self.calls.wrapping_mul(self.c[39]));
            for i in 0..3 {
                self.put(a[3] as usize + i, 1, pattern >> (8 * i));
            }
        }
        if k == 6 {
            self.put(a[2] as usize, 2, self.c[38]);
        }
        let v = if k == 3 {
            let v = self.c[13 + self.capreads.min(1)];
            self.capreads += 1;
            v
        } else if k == 5 {
            self.c[18]
        } else {
            0
        };
        self.mutate();
        v
    }
}
thread_local! {static STATE:RefCell<Option<State>>=const{RefCell::new(None)};}
fn state<T>(f: impl FnOnce(&mut State) -> T) -> T {
    STATE.with(|s| f(s.borrow_mut().as_mut().unwrap()))
}
struct Backend;
impl production::Access for Backend {
    unsafe fn param() -> usize {
        0x200000
    }
    unsafe fn read(a: usize, w: usize) -> u32 {
        state(|s| s.read(a, w))
    }
    unsafe fn write(a: usize, w: usize, v: u32) {
        state(|s| s.write(a, w, v));
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
            arity(o);
            s.event(5, &[o as u32, g as u32]);
            0x71000000 + g * 0x1000 + o
        })
    }
    unsafe fn read_call<const N: usize>(t: usize, a: [u32; N]) -> u32 {
        state(|s| s.callback(t, &a))
    }
    unsafe fn write_call<const N: usize>(t: usize, a: [u32; N]) {
        state(|s| s.callback(t, &a));
    }
    unsafe fn external<const N: usize>(k: u32, a: [u32; N]) -> u32 {
        state(|s| s.external(k, &a))
    }
    unsafe fn internal<const N: usize>(k: u32, a: [u32; N]) {
        let (before, run) = state(|s| {
            let before = s.bindings.len();
            let clean = s.clean_args(k, &a);
            let mut args = vec![k];
            args.extend(clean);
            s.event(9, &args);
            (before, s.c[33] & (1 << k) != 0)
        });
        if run {
            unsafe {
                dispatch(k, &a);
            }
        } else {
            state(|s| {
                if k == 7 {
                    for (array, index) in [0, 1, 2, 3, 4, 5, 6, 8].into_iter().enumerate() {
                        for i in 0..if S3 { a[7] & 255 } else { a[7] } {
                            s.put(
                                a[index] as usize + i as usize,
                                1,
                                initial_byte(&s.c, array, i as usize),
                            );
                        }
                    }
                }
                s.mutate();
            });
        }
        state(|s| s.bindings.truncate(before));
    }
    unsafe fn scratch<F: FnOnce(usize)>(kind: u32, f: F) {
        let base = if kind == 0 { 0x108000 } else { 0x10a000 };
        f(base);
    }
    unsafe fn local_read(a: usize, w: usize) -> u32 {
        state(|s| s.get(a, w))
    }
    unsafe fn local_write(a: usize, w: usize, v: u32) {
        state(|s| s.put(a, w, v));
    }
}
unsafe fn dispatch(k: u32, a: &[u32]) {
    state(|s| s.contexts.push(k));
    unsafe {
        match k {
            0 => production::wait::<Backend>(),
            1 => production::disable::<Backend>(),
            2 => production::enable::<Backend>(),
            3 => production::memory::<Backend>(a[0], a[1] as usize),
            4 | 7 => {
                let p = core::array::from_fn(|i| a[if i == 7 { 8 } else { i }] as usize);
                if k == 4 {
                    production::write_i2c::<Backend>(p, a[7]);
                } else {
                    production::read_i2c::<Backend>(p, a[7]);
                }
            }
            5 => production::cap_memory::<Backend>(a[0]),
            6 => production::initialize::<Backend>(),
            8 => production::program_i2c::<Backend>(),
            9 => production::hardware_init::<Backend>(a[0], a[1]),
            10 => production::software_start::<Backend>(a[0], a[1], a[2]),
            _ => panic!(),
        }
    }
    state(|s| s.contexts.pop());
}
fn run(c: [u32; 48]) -> Vec<u32> {
    let mut a = c[1..10].to_vec();
    let p = pointers(&c);
    if c[0] == 3 {
        a[1] = p[0] as u32;
    }
    if [4, 7].contains(&c[0]) {
        for (i, index) in [0, 1, 2, 3, 4, 5, 6, 8].into_iter().enumerate() {
            a[index] = p[i] as u32;
        }
    }
    STATE.with(|s| *s.borrow_mut() = Some(State::new(c)));
    unsafe {
        dispatch(c[0], &a);
    }
    state(|s| std::mem::take(&mut s.trace))
}
#[test]
fn matches_original_instructions() {
    let path = std::env::var("PHY_HW_FREQ_CASES").expect("case path");
    let bytes = fs::read(path).unwrap();
    assert_eq!(bytes.len() % 4, 0);
    let words: Vec<_> = bytes
        .chunks_exact(4)
        .map(|b| u32::from_le_bytes(b.try_into().unwrap()))
        .collect();
    let mut at = 0;
    let mut count = 0;
    while at < words.len() {
        let c: [u32; 48] = words[at..at + 48].try_into().unwrap();
        at += 48;
        let n = words[at] as usize;
        at += 1;
        let want = &words[at..at + n];
        at += n;
        let got = run(c);
        if got != want {
            let index = got
                .iter()
                .zip(want)
                .position(|(a, b)| a != b)
                .unwrap_or(got.len().min(want.len()));
            let start = index / 12 * 12;
            panic!(
                "case {count} {c:?} first event {} actual {:?} expected {:?} lengths {}/{}",
                start / 12,
                got.get(start..(start + 12).min(got.len())),
                want.get(start..(start + 12).min(want.len())),
                got.len(),
                want.len()
            );
        }
        count += 1;
    }
    assert_eq!(
        count,
        std::env::var("PHY_HW_FREQ_CASE_COUNT")
            .unwrap()
            .parse::<usize>()
            .unwrap()
    );
    println!("{count} original instruction cases passed");
}
