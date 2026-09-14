#![allow(dead_code)]
use std::{cell::RefCell, collections::BTreeMap, fs};
#[path = "../../../esp-wifi-hal/src/phy_reg.rs"]
mod production;
const S3: bool = cfg!(esp32s3);
fn fields() -> Vec<(usize, usize)> {
    let mut v: Vec<_> = (0..6)
        .map(|i| (if S3 { 0x2ac } else { 0x328 } + i * 4, 4))
        .collect();
    v.extend(if S3 {
        vec![(0x2a1, 1)]
    } else {
        vec![(0x1f5, 1), (0x1f6, 1), (0x31d, 1), (0x31e, 1)]
    });
    v
}
fn mmio() -> Vec<usize> {
    let mut v: Vec<_> = [
        0, 0x24, 0x28, 0x2c, 0x30, 0x40, 0x44, 0x4c, 0x50, 0x64, 0x68, 0x70, 0x7c, 0x90, 0xe0,
        0xe4, 0xe8, 0xec, 0xf0, 0xf4, 0xf8, 0xfc, 0x110, 0x1e4,
    ]
    .map(|o| 0x60006000 + o)
    .into();
    v.extend([0x6000e048, 0x6000e058, 0x6000e060]);
    v.extend(
        [
            0x1c, 0x34, 0x44, 0x5c, 0x68, 0x80, 0x94, 0xa4, 0x104, 0x124, 0x134, 0x13c, 0x1b0,
            0x400, 0x804, 0x850, 0xc98,
        ]
        .map(|o| 0x6001c000 + o),
    );
    v.extend([0x6001d000, 0x6001d030, 0x6001d06c, 0x6002600c, 0x60026010]);
    v
}
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
            self.mem.insert(a + i, (v >> (8 * i)) as u8);
        }
    }
    fn get(&self, a: usize, w: usize) -> u32 {
        (0..w).fold(0, |v, i| {
            v | (*self
                .mem
                .get(&(a + i))
                .unwrap_or_else(|| panic!("uninitialized {a:x}/{w}")) as u32)
                << (8 * i)
        })
    }
    fn event(&mut self, k: u32, args: &[u32]) {
        assert!(args.len() <= 7);
        self.trace.push(k);
        self.trace.extend(args);
        self.trace.extend(std::iter::repeat_n(0, 7 - args.len()));
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
        for (o, w) in fields() {
            s.put(0x200000 + o, w, c[17].wrapping_add((o as u32) * 0x1021));
        }
        if S3 {
            s.put(0x2002a1, 1, c[20]);
        } else {
            for (o, v) in [
                (0x1f6, c[18]),
                (0x1f5, c[19]),
                (0x31d, c[20]),
                (0x31e, c[21]),
            ] {
                s.put(0x200000 + o, 1, v);
            }
        }
        for i in 0..14 {
            s.put(
                0x300000 + c[16] as usize + i,
                1,
                c[17].wrapping_add(i as u32 * 17),
            );
        }
        for a in mmio() {
            s.put(a, 4, c[7] ^ (a as u32).wrapping_mul(0x1021));
        }
        s
    }
    fn change(&mut self) {
        for (o, w) in fields() {
            self.put(
                0x200000 + o,
                w,
                self.get(0x200000 + o, w) ^ self.c[11].wrapping_add(o as u32 * 17),
            );
        }
        for i in 0..14 {
            let a = 0x300000 + self.c[16] as usize + i;
            self.put(
                a,
                1,
                self.get(a, 1) ^ self.c[11].wrapping_add(i as u32 * 17),
            );
        }
    }
    fn mutate(&mut self) {
        let m = 1 << (self.calls % 32);
        if self.c[12] & m != 0 {
            self.generation += 1;
        }
        if self.c[13] & m != 0 {
            self.change();
        }
        if self.c[14] & m != 0 {
            for a in mmio() {
                self.put(
                    a,
                    4,
                    self.get(a, 4) ^ self.c[11].wrapping_add((a as u32).wrapping_mul(17)),
                );
            }
        }
        self.calls += 1;
    }
}
thread_local! { static STATE:RefCell<Option<State>>=const {RefCell::new(None)}; }
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
            if mmio().contains(&a) {
                assert_eq!(w, 4);
                let v = s.get(a, w) ^ s.c[8].wrapping_mul(s.mmreads);
                s.event(7, &[a as u32, v]);
                if s.c[10] & (1 << (s.mmreads % 32)) != 0 {
                    s.change();
                }
                s.mmreads += 1;
                v
            } else {
                let v = s.get(a, w);
                s.event(1, &[a as u32, w as u32, v]);
                v
            }
        })
    }
    unsafe fn write(a: usize, w: usize, v: u32) {
        state(|s| {
            assert!(mmio().contains(&a));
            assert_eq!(w, 4);
            s.event(8, &[a as u32, v]);
            s.put(a, w, v);
            if s.c[9] & (1 << (s.mmwrites % 32)) != 0 {
                s.change();
            }
            s.mmwrites += 1;
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
            assert_eq!(o, if S3 { 0x190 } else { 0x1b4 });
            s.event(5, &[o as u32, g as u32]);
            0x71000000 + g * 0x1000 + o
        })
    }
    unsafe fn call(t: usize, a: [u32; 4]) {
        state(|s| {
            s.event(6, &[t as u32, a[0], a[1], a[2], a[3]]);
            s.mutate();
        });
    }
    unsafe fn internal(k: u32) {
        let execute = state(|s| {
            s.event(9, &[k]);
            let exec = s.c[15] & (1 << k) != 0;
            if !exec {
                s.mutate();
            }
            exec
        });
        if execute {
            unsafe {
                match k {
                    2 => production::btbb::<Mock>(),
                    3 => production::agc_options::<Mock>(),
                    _ => panic!(),
                }
            }
        }
    }
    unsafe fn delay(us: u32) {
        state(|s| {
            assert_eq!(us, 1);
            s.event(10, &[0, us]);
            s.mutate();
        });
    }
}
unsafe fn invoke(c: [u32; 32]) -> u32 {
    unsafe {
        match c[0] {
            0 => production::pbus::<Mock>(),
            1 => {
                #[cfg(esp32c3)]
                production::paon::<Mock>();
                #[cfg(esp32s3)]
                production::digital_gain::<Mock>(0x300000 + c[16] as usize);
            }
            2 => production::btbb::<Mock>(),
            3 => production::agc_options::<Mock>(),
            4 => production::options_11b::<Mock>(c[1]),
            5 => production::disable_agc::<Mock>(),
            6 => production::enable_agc::<Mock>(),
            7 => production::renew::<Mock>(),
            8 => production::wifi_enable::<Mock>(c[1]),
            9 => return production::tx_iq::<Mock>(c[1], c[2]),
            10 => return production::rx_iq::<Mock>(c[1], c[2]),
            11 => production::start_tone::<Mock>(c[1..7].try_into().unwrap()),
            12 => production::stop_tone::<Mock>(c[1]),
            13 => production::noise_floor::<Mock>(),
            14 => production::frequency_correct::<Mock>(c[1], c[2]),
            15 => production::force_off::<Mock>(c[1]),
            _ => panic!(),
        }
    }
    0
}
#[test]
fn production_matches_original_instruction_effects() {
    let bytes = fs::read(std::env::var("PHY_REG_CASES").unwrap()).unwrap();
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
            let start = i / 8 * 8;
            panic!(
                "case {count} kind {} {c:x?} trace word {i}: actual {:?}, expected {:?}; lengths {}/{}",
                c[0],
                trace.get(start..(start + 8).min(trace.len())),
                want.get(start..(start + 8).min(want.len())),
                trace.len(),
                want.len()
            );
        }
        offset += len;
        count += 1;
    }
    assert_eq!(
        count,
        std::env::var("PHY_REG_CASE_COUNT")
            .unwrap()
            .parse::<usize>()
            .unwrap()
    );
}
