#![allow(dead_code)]
use std::{cell::RefCell, collections::BTreeMap, fs};
#[cfg(esp32s3)]
#[path = "../../../esp-wifi-hal/src/phy_basic.rs"]
mod basic;
#[path = "../../../esp-wifi-hal/src/phy_tx_gain.rs"]
mod production;
#[cfg(esp32s3)]
#[path = "../../../esp-wifi-hal/src/phy_reg.rs"]
mod reg;
#[cfg(esp32s3)]
use production::Access;
const S3: bool = cfg!(esp32s3);
const MMIO: [usize; 4] = [0x60006024, 0x60006028, 0x6000602c, 0x60006030];
struct State {
    c: [u32; 48],
    mem: BTreeMap<usize, u8>,
    trace: Vec<u32>,
    generation: u32,
    calls: u32,
    reads: u32,
    writes: u32,
}
impl State {
    fn put(&mut self, a: usize, w: usize, v: u32) {
        for i in 0..w {
            self.mem.insert((a + i) & 0xffff_ffff, (v >> (i * 8)) as u8);
        }
    }
    fn get(&self, a: usize, w: usize) -> u32 {
        (0..w).fold(0, |v, i| {
            v | ((*self
                .mem
                .get(&((a + i) & 0xffff_ffff))
                .unwrap_or_else(|| panic!("uninitialized {a:x}/{w}")) as u32)
                << (8 * i))
        })
    }
    fn event(&mut self, k: u32, a: &[u32]) {
        assert!(a.len() <= 15);
        self.trace.push(k);
        self.trace.extend(a);
        self.trace.extend(std::iter::repeat_n(0, 15 - a.len()));
    }
    fn observed(a: usize, w: usize) -> bool {
        (0x200000 <= a && a + w <= 0x200000 + if S3 { 740 } else { 848 })
            || (0x280000 <= a && a + w <= 0x28002a)
            || [
                0x300000, 0x310000, 0x320000, 0x330000, 0x340000, 0x350000, 0x360000,
            ]
            .iter()
            .any(|b| b - 512 <= a && a + w <= b + 2048)
    }
    fn new(c: [u32; 48]) -> Self {
        let mut s = Self {
            c,
            mem: BTreeMap::new(),
            trace: vec![],
            generation: 0,
            calls: 0,
            reads: 0,
            writes: 0,
        };
        for i in 0..if S3 { 740 } else { 848 } {
            s.put(0x200000 + i, 1, c[9].wrapping_add(i as u32 * 17));
        }
        for i in 0..42 {
            s.put(0x280000 + i, 1, c[6].wrapping_add(i as u32 * 7));
        }
        for b in [
            0x300000, 0x310000, 0x320000, 0x330000, 0x340000, 0x350000, 0x360000,
        ] {
            for i in -512i32..2048 {
                s.put(
                    (b as i32 + i) as usize,
                    1,
                    c[6].wrapping_add(i.wrapping_mul(17) as u32),
                );
            }
        }
        for i in 0..256 {
            let threshold = match c[7] {
                1 => c[37].wrapping_sub(i as u32),
                2 => c[37],
                3 => (i as u32 * 8).wrapping_sub(c[37]),
                4 => c[37]
                    .wrapping_add((i as u32 % 3) * 16)
                    .wrapping_sub(i as u32 * 8),
                _ => c[37].wrapping_sub(i as u32 * 8),
            };
            s.put(0x340000 + i * 2, 2, threshold);
            s.put(0x330000 + i * 2, 2, c[26].wrapping_add(i as u32 * 11));
            s.put(0x320000 + i, 1, c[25].wrapping_add(i as u32 * 13));
        }
        for i in 0..18 {
            s.put(0x200000 + 14 + i, 1, c[25].wrapping_add(i as u32 * 13));
            s.put(0x200000 + 32 + i * 2, 2, c[26].wrapping_add(i as u32 * 11));
            s.put(0x200000 + 68 + i * 2, 2, c[37].wrapping_sub(i as u32 * 8));
        }
        for i in 0..14 {
            s.put(0x200000 + 0x68 + i, 1, c[25].wrapping_add(i as u32 * 7));
            s.put(0x200000 + 0x76 + i * 2, 2, c[37].wrapping_sub(i as u32 * 8));
        }
        for (o, v) in [
            (0x99, c[17]),
            (0x104, c[18]),
            (0x98, c[19]),
            (0x217, c[21]),
            (0x20d, c[22]),
            (0x2c8, c[23]),
            (0x2c9, c[33]),
            (0x1fb, c[31]),
            (0x1fc, c[31]),
            (0x9a, c[32]),
            (0x175, c[33]),
            (0x17c, c[33]),
        ] {
            s.put(0x200000 + o, 1, v);
        }
        for i in 0..3 {
            let v = c[38] >> (i * 8);
            s.put(0x300000 + i, 1, v);
            s.put(0x350000 + i, 1, v);
        }
        if c[0] == 11 {
            s.put(0x300000, 2, c[1]);
            s.put(0x310000, 2, c[2]);
        }
        for a in MMIO {
            s.put(a, 4, c[9] ^ a as u32);
        }
        s
    }
    fn change(&mut self) {
        for o in [0x217, 0x98, 0x1fb, 0x9a, 0x175, 0x1fc, 0x17c, 0x2c9] {
            let v = self.get(0x200000 + o, 1) ^ self.c[24].wrapping_add(o as u32 * 17);
            self.put(0x200000 + o, 1, v);
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
    unsafe fn global(k: u32) -> usize {
        assert_eq!(k, 0);
        0x280000
    }
    unsafe fn read(a: usize, w: usize) -> u32 {
        let a = a & 0xffff_ffff;
        state(|s| {
            let v = s.get(a, w);
            if MMIO.contains(&a) {
                assert_eq!(w, 4);
                s.event(7, &[a as u32, v]);
            } else if State::observed(a, w) {
                s.event(1, &[a as u32, w as u32, v]);
            } else {
                assert!((0x500000..0x506000).contains(&a));
            }
            if State::observed(a, w) || MMIO.contains(&a) {
                if s.c[10] & (1 << (s.reads % 32)) != 0 {
                    s.change();
                }
                s.reads += 1;
            }
            v
        })
    }
    unsafe fn write(a: usize, w: usize, v: u32) {
        let a = a & 0xffff_ffff;
        state(|s| {
            let v = if w == 4 { v } else { v & ((1 << (w * 8)) - 1) };
            if MMIO.contains(&a) {
                assert_eq!(w, 4);
                s.event(8, &[a as u32, v]);
            } else if State::observed(a, w) {
                s.event(2, &[a as u32, w as u32, v]);
            } else {
                assert!((0x500000..0x506000).contains(&a));
            }
            s.put(a, w, v);
            if State::observed(a, w) || MMIO.contains(&a) {
                if s.c[12] & (1 << (s.writes % 32)) != 0 {
                    s.change();
                }
                s.writes += 1;
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
    unsafe fn call(t: usize, a: &[usize], returns: bool) -> u32 {
        let slot = (t - 0x71000000) % 0x1000;
        let (route, value) = state(|s| {
            assert!((t - 0x71000000) / 0x1000 <= s.generation as usize);
            let mut args = vec![t as u32];
            args.extend(a.iter().enumerate().map(|(i, v)| {
                if S3 && slot == 0x228 && i == 11 {
                    0
                } else {
                    *v as u32
                }
            }));
            s.event(6, &args);
            let route = if S3 {
                match slot {
                    0xfc => Some(13),
                    0x228 => Some(6),
                    0x224 => Some(0),
                    0x218 => Some(5),
                    0x270 => Some(8),
                    _ => None,
                }
            } else if slot == 0x128 {
                Some(2)
            } else {
                None
            };
            let route = route.filter(|k| s.c[39] & (1 << k) != 0);
            let expected = if S3 {
                match slot {
                    0x28 => 3,
                    0xfc => 2,
                    0xdc | 0xe0 | 0x224 | 0x214 | 0x270 => 1,
                    0x228 => 13,
                    0x210 => 6,
                    0x218 => 11,
                    _ => panic!("Unknown slot"),
                }
            } else {
                match slot {
                    0x28 => 3,
                    0x110 => 2,
                    0x128 => 4,
                    _ => panic!("Unknown slot"),
                }
            };
            assert_eq!(a.len(), expected);
            assert_eq!(
                returns,
                if S3 {
                    [0x28, 0xfc, 0xdc, 0xe0].contains(&slot)
                } else {
                    [0x28, 0x110].contains(&slot)
                }
            );
            (
                route,
                if returns {
                    (if S3 && slot == 0xdc { s.c[36] } else { s.c[15] })
                        .wrapping_add(s.calls.wrapping_mul(s.c[16]))
                } else {
                    0
                },
            )
        });
        let result = if let Some(k) = route {
            unsafe { Self::child(k, a) }
        } else if !S3 && slot == 0x128 {
            let c = state(|s| s.c);
            for i in 0..4 {
                unsafe {
                    Self::write(
                        a[1] + i,
                        1,
                        c[25].wrapping_add((i as u32).wrapping_mul(c[16])),
                    );
                }
            }
            0
        } else {
            value
        };
        state(|s| {
            s.mutate();
            s.event(14, &[t as u32, result]);
        });
        result
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
    unsafe fn local(_p: *mut u32, tag: usize, size: usize) -> usize {
        assert!(tag <= 5);
        assert_eq!(size, [16, 4, 16, 16, 48, 224][tag]);
        0x500000 + tag * 0x1000
    }
    unsafe fn copy(d: usize, o: usize, n: usize) {
        state(|s| {
            for i in 0..n {
                s.put(d + i, 1, production::CONSTANTS[o + i].into());
            }
        });
    }
    unsafe fn child(k: u32, a: &[usize]) -> u32 {
        let c = state(|s| {
            let mut args = vec![k];
            args.extend(
                a.iter()
                    .enumerate()
                    .map(|(i, v)| if k == 6 && i == 11 { 0 } else { *v as u32 }),
            );
            s.event(9, &args);
            s.c
        });
        if c[20] & (1 << k) != 0 {
            return unsafe { invoke(k, a) };
        }
        let result = unsafe {
            match k {
                4 => {
                    let ptrs = if S3 { &a[3..6] } else { &a[1..4] };
                    for ((p, w), v) in ptrs.iter().zip([1, 2, 2]).zip(&c[25..28]) {
                        Self::write(*p, w, *v);
                    }
                    if S3 { c[28] } else { 0 }
                }
                2 => {
                    for i in 0..4 {
                        Self::write(
                            a[1] + i,
                            1,
                            c[25].wrapping_add((i as u32).wrapping_mul(c[16])),
                        );
                    }
                    0
                }
                3 => {
                    for i in 0..14 {
                        Self::write(
                            a[2] + i,
                            1,
                            c[25].wrapping_add((i as u32).wrapping_mul(c[16])),
                        );
                    }
                    0
                }
                11 => {
                    Self::write(a[0], 2, c[26]);
                    Self::write(a[1], 2, c[27]);
                    0
                }
                1 | 13 => c[15],
                _ => 0,
            }
        };
        state(|s| s.mutate());
        result
    }
}
#[cfg(esp32s3)]
impl reg::Access for Mock {
    unsafe fn param() -> usize {
        0x200000
    }
    unsafe fn read(a: usize, w: usize) -> u32 {
        unsafe { <Self as Access>::read(a, w) }
    }
    unsafe fn write(a: usize, w: usize, v: u32) {
        unsafe { <Self as Access>::write(a, w, v) }
    }
    unsafe fn table() -> usize {
        panic!()
    }
    unsafe fn slot(_: usize, _: usize) -> usize {
        panic!()
    }
    unsafe fn call(_: usize, _: [u32; 4]) {
        panic!()
    }
    unsafe fn internal(_: u32) {
        panic!()
    }
    unsafe fn delay(_: u32) {
        panic!()
    }
}
#[cfg(esp32s3)]
struct Calibration(usize);
#[cfg(esp32s3)]
impl basic::Calibration for Calibration {
    unsafe fn read(&self, i: usize) -> u8 {
        unsafe { Mock::read(self.0 + i, 1) as u8 }
    }
}
unsafe fn invoke(k: u32, a: &[usize]) -> u32 {
    unsafe {
        match k {
            0 => production::digital::<Mock>(a[0]),
            1 => return production::interpolate::<Mock>(a[0], a[1] as u32),
            2 => production::fcc::<Mock>(a),
            3 => production::limits::<Mock>(a),
            4 => return production::lookup::<Mock>(a),
            5 => production::bt_get::<Mock>(a),
            6 => production::wifi_get::<Mock>(a),
            7 => production::wifi_set::<Mock>(a[0], a[1]),
            8 => production::bt_set::<Mock>(a[0]),
            9 => production::bt_initialize::<Mock>(),
            10 => production::calibration_tables::<Mock>(),
            #[cfg(esp32s3)]
            11 => production::dig_check::<Mock>(a[0], a[1]),
            #[cfg(esp32s3)]
            12 => reg::digital_gain::<Mock>(a[0]),
            #[cfg(esp32s3)]
            13 => return basic::interpolate(&Calibration(a[0]), a[1] as u32),
            _ => panic!(),
        }
    };
    0
}
fn arguments(c: [u32; 48]) -> Vec<usize> {
    let (mut x, mut y, mut z) = (0x310000, 0x310010, 0x310020);
    let mut out = 0x310000;
    if c[8] == 1 {
        out = 0x300000;
        x = 0x320000;
        y = 0x330000;
        z = 0x340000;
    } else if c[8] == 2 {
        out = 0x300002;
        x = 0x310000;
        y = x;
        z = x;
    } else if c[8] == 3 {
        out = 0x320002;
        x = 0x340002;
        y = 0x340004;
        z = 0x340006;
    }
    let a = match c[0] {
        0 | 12 => vec![0x300000],
        1 | 13 => vec![0x300000, c[1]],
        2 => vec![c[1], out, 0x320000, 0x330000],
        3 => vec![c[1], c[2], out, 0x300000, c[3], 0x320000, 0x330000],
        4 => {
            if S3 {
                vec![
                    c[3], c[4], c[1], x, y, z, 0x320000, 0x330000, 0x340000, c[2], c[5],
                ]
            } else {
                vec![c[1], x, y, z, 0x320000, 0x330000, 0x340000, c[2]]
            }
        }
        5 => vec![
            0x300000, c[1], c[2], 0x320000, 0x330000, 0x340000, out, 0x310040, c[35], c[34], c[4],
        ],
        6 => vec![
            c[1], 0x350000, 0x300000, c[2], c[3], 0x320000, 0x330000, 0x340000, out, 0x310040,
            0x310080, 0x360000, c[4],
        ],
        7 => vec![c[1], c[4]],
        8 => vec![c[4]],
        9 | 10 => vec![],
        11 => vec![0x300000, if c[8] != 0 { 0x300000 } else { 0x310000 }],
        _ => panic!(),
    };
    a.into_iter().map(|v| v as usize).collect()
}
#[test]
fn production_matches_original_instruction_effects() {
    let bytes = fs::read(std::env::var("PHY_TX_GAIN_CASES").unwrap()).unwrap();
    assert_eq!(bytes.len() % 4, 0);
    let words: Vec<_> = bytes
        .chunks_exact(4)
        .map(|b| u32::from_le_bytes(b.try_into().unwrap()))
        .collect();
    let (mut offset, mut count) = (0, 0);
    while offset < words.len() {
        let c: [u32; 48] = words[offset..offset + 48].try_into().unwrap();
        let expected = words[offset + 48];
        let len = words[offset + 49] as usize;
        offset += 50;
        STATE.with(|s| *s.borrow_mut() = Some(State::new(c)));
        let result = unsafe { invoke(c[0], &arguments(c)) };
        assert_eq!(result, expected, "case {count} {c:x?}");
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
        std::env::var("PHY_TX_GAIN_CASE_COUNT")
            .unwrap()
            .parse::<usize>()
            .unwrap()
    );
}

#[test]
fn opaque_callback_and_child_outputs_wrap_like_machine_words() {
    for kind in [2, 3] {
        let mut c = [0u32; 48];
        c[16] = u32::MAX;
        STATE.with(|s| *s.borrow_mut() = Some(State::new(c)));
        let mut args = [0usize; 7];
        args[if kind == 2 { 1 } else { 2 }] = 0x310000;
        unsafe {
            <Mock as production::Access>::child(kind, &args);
        }
        assert_eq!(
            state(|s| (0..4).map(|i| s.get(0x310000 + i, 1)).collect::<Vec<_>>()),
            [0, 255, 254, 253]
        );
    }
    if !S3 {
        let mut c = [0u32; 48];
        c[16] = u32::MAX;
        STATE.with(|s| *s.borrow_mut() = Some(State::new(c)));
        unsafe {
            <Mock as production::Access>::call(
                0x71000128,
                &[1, 0x310000, 0x320000, 0x330000],
                false,
            );
        }
        assert_eq!(
            state(|s| (0..4).map(|i| s.get(0x310000 + i, 1)).collect::<Vec<_>>()),
            [0, 255, 254, 253]
        );
    }
}
