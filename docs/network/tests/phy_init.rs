#![allow(dead_code)]
use std::{cell::RefCell, collections::BTreeMap, fs};
#[path = "../../../esp-wifi-hal/src/phy_init.rs"]
mod production;
use production::Access;
include!("phy_init_contracts.rs");
const S3: bool = cfg!(esp32s3);
const MASK: usize = 0xffff_ffff;
const MMIO: [usize; 4] = [0x6000e130, 0x60006110, 0x6001cd0c, 0x60007050];
struct State {
    c: [u32; 48],
    mem: BTreeMap<usize, u8>,
    trace: Vec<u32>,
    calls: u32,
    reads: u32,
    writes: u32,
    generation: u32,
}
impl State {
    fn put(&mut self, a: usize, w: usize, v: u32) {
        for i in 0..w {
            self.mem.insert((a + i) & MASK, (v >> (i * 8)) as u8);
        }
    }
    fn get(&self, a: usize, w: usize) -> u32 {
        if (0x70000000..0x70400000).contains(&a) && (0..w).all(|i| !self.mem.contains_key(&(a + i)))
        {
            assert_eq!(w, 4);
            assert_eq!(a % 4, 0);
            return (0x71000000 + a - 0x70000000) as u32;
        }
        (0..w).fold(0, |v, i| {
            v | ((*self
                .mem
                .get(&((a + i) & MASK))
                .unwrap_or_else(|| panic!("uninitialized {a:x}/{w}")) as u32)
                << (i * 8))
        })
    }
    fn event(&mut self, k: u32, args: &[u32]) {
        assert!(args.len() <= 15);
        self.trace.push(k);
        self.trace.extend(args);
        self.trace.extend(std::iter::repeat_n(0, 15 - args.len()));
    }
    fn observed(a: usize, w: usize) -> bool {
        (0x200000 <= a && a + w <= 0x200000 + production::PARAM_SIZE)
            || (0x210000 <= a && a + w <= 0x21002a)
            || matches!(a, 0x220000 | 0x230000)
            || [0x300000, 0x310000, 0x320000]
                .iter()
                .any(|b| *b <= a && a + w <= b + 1024)
            || (0x70000000..0x70400000).contains(&a)
            || MMIO.contains(&a)
    }
    fn snapshot(&mut self, a: usize, n: usize) {
        if !(0x500000..0x508000).contains(&a) {
            return;
        }
        for offset in (0..n).step_by(12) {
            let end = (offset + 12).min(n);
            let mut row = vec![(a + offset) as u32, (end - offset) as u32];
            row.extend((offset..end).map(|i| self.get(a + i, 1)));
            self.event(11, &row);
        }
    }
    fn change(&mut self) {
        let a = 0x200000 + self.c[8] as usize;
        let v = self.get(a, 1);
        self.put(a, 1, v ^ self.c[9]);
    }
    fn mutate(&mut self) {
        if self.c[12] & (1 << (self.calls % 32)) != 0 {
            self.change();
        }
        if self.c[13] & (1 << (self.calls % 32)) != 0 {
            self.generation += 1;
            self.put(0x220000, 4, 0x70000000 + self.generation * 0x1000);
        }
        self.calls += 1;
    }
    fn new(c: [u32; 48]) -> Self {
        let mut s = Self {
            c,
            mem: BTreeMap::new(),
            trace: vec![],
            calls: 0,
            reads: 0,
            writes: 0,
            generation: 0,
        };
        for i in 0..production::PARAM_SIZE {
            s.put(0x200000 + i, 1, c[4].wrapping_add(i as u32 * 17));
        }
        for (a, n) in [(0x210000, 42), (0x220000, 4), (0x230000, 1)] {
            if S3 && a == 0x230000 {
                continue;
            }
            for i in 0..n {
                s.put(a + i, 1, c[4].wrapping_add(i as u32 * 7));
            }
        }
        s.put(0x220000, 4, 0x70000000);
        for b in [0x300000, 0x310000, 0x320000] {
            for i in 0..1024 {
                s.put(
                    b + i,
                    1,
                    (if b == 0x320000 { c[21] } else { c[4] }).wrapping_add(i as u32 * 17),
                );
            }
        }
        for (offset, v, w) in [
            (288, c[5], 4),
            (229, c[6], 1),
            (162, c[2], 1),
            (170, c[7], 1),
            (498, c[7], 1),
            (525, c[7], 1),
            (286, c[7], 1),
            (if S3 { 674 } else { 799 }, c[7], 1),
            (if S3 { 675 } else { 800 }, c[7], 1),
            (if S3 { 679 } else { 804 }, c[7], 1),
        ] {
            s.put(0x200000 + offset, w, v);
        }
        if S3 {
            s.put(0x200000 + 729, 1, c[7]);
        }
        for (i, v) in READONLY.iter().enumerate() {
            s.put(0x240000 + i, 1, *v as u32);
        }
        for a in MMIO {
            s.put(
                a,
                4,
                if a == 0x60007050 {
                    c[23]
                } else {
                    c[5] ^ a as u32
                },
            );
        }
        s.put(0x310000, 4, c[3]);
        let checksum = !(0..production::PARAM_SIZE + 12)
            .step_by(4)
            .fold(0u32, |v, i| v.wrapping_add(s.get(0x310000 + i, 4)));
        s.put(0x310000 + production::PARAM_SIZE + 12, 4, checksum ^ c[16]);
        s
    }
}
thread_local! {static STATE:RefCell<Option<State>>=const {RefCell::new(None)};}
fn state<T>(f: impl FnOnce(&mut State) -> T) -> T {
    STATE.with(|s| f(s.borrow_mut().as_mut().unwrap()))
}
struct Mock;
impl Access for Mock {
    unsafe fn symbol(name: &str) -> usize {
        SYMBOLS
            .iter()
            .find(|(n, _)| *n == name)
            .unwrap_or_else(|| panic!("unknown symbol {name}"))
            .1
    }
    unsafe fn read(a: usize, w: usize) -> u32 {
        state(|s| {
            let v = s.get(a, w);
            if State::observed(a, w) {
                s.event(1, &[a as u32, w as u32, v]);
                if s.c[10] & (1 << (s.reads % 32)) != 0 {
                    s.change();
                }
                s.reads += 1;
            }
            v
        })
    }
    unsafe fn write(a: usize, w: usize, v: u32) {
        state(|s| {
            let v = if w == 4 { v } else { v & ((1 << (w * 8)) - 1) };
            let observed = State::observed(a, w);
            if observed {
                s.event(2, &[a as u32, w as u32, v]);
            }
            s.put(a, w, v);
            if observed {
                if s.c[11] & (1 << (s.writes % 32)) != 0 {
                    s.change();
                }
                s.writes += 1;
            }
        });
    }
    unsafe fn local(_p: *mut u32, tag: usize, _n: usize) -> usize {
        0x500000 + tag * 0x1000
    }
    unsafe fn readonly(offset: usize) -> usize {
        0x240000 + offset
    }
    unsafe fn copy(d: usize, src: usize, n: usize) {
        state(|s| {
            assert!(d + n <= src || src + n <= d);
            if State::observed(d, n) {
                s.event(7, &[d as u32, src as u32, n as u32]);
            }
            for i in 0..n {
                let v = s.get(src + i, 1);
                s.put(d + i, 1, v);
            }
        });
    }
    unsafe fn clear(d: usize, n: usize) {
        state(|s| {
            if State::observed(d, n) {
                s.event(8, &[d as u32, n as u32]);
            }
            for i in 0..n {
                s.put(d + i, 1, 0);
            }
        });
    }
    unsafe fn child(kind: u32, args: &[usize]) -> u32 {
        let mocked = state(|s| {
            if kind == 2 {
                s.snapshot(args[0], 77);
            }
            if kind == 6 && args[2] != 0 {
                s.snapshot(args[1], 93);
            }
            let mut row = vec![kind];
            row.extend(
                args.iter()
                    .enumerate()
                    .map(|(i, v)| if kind == 8 && i == 2 { 0 } else { *v as u32 }),
            );
            s.event(3, &row);
            s.c[17] & (1 << kind) != 0
        });
        let v = if mocked {
            state(|s| {
                let v = s.c[18]
                    % match kind {
                        6 => 46,
                        8 => 2,
                        14 => 8,
                        _ => 1,
                    };
                if kind == 6 && args[2] == 0 {
                    for i in 0..93 {
                        s.put(args[1] + i, 1, s.c[14].wrapping_add(i as u32 * 13));
                    }
                }
                s.mutate();
                v
            })
        } else {
            unsafe { production::dispatch::<Mock>(kind, args) }
        };
        state(|s| s.event(4, &[kind, v]));
        v
    }
    unsafe fn call(target: usize, args: &[usize], _returns: bool) -> u32 {
        if (0x750000..0x750120).contains(&target) {
            return unsafe { Self::child(((target - 0x750000) / 16) as u32, args) };
        }
        state(|s| {
            if (0x760000..0x761000).contains(&target) {
                let id = ((target - 0x760000) / 16) as u32;
                let (_, name, n) = HELPERS
                    .iter()
                    .find(|(i, _, _)| *i == id)
                    .unwrap_or_else(|| panic!("unknown helper {id}"));
                assert_eq!(args.len(), *n, "arity {name}");
                let mut row = vec![id];
                row.extend(args.iter().map(|v| *v as u32));
                s.event(5, &row);
                let mut v = 0;
                match *name {
                    "phy_get_romfuncs" => v = 0x70000000 + s.generation * 0x1000,
                    "chip726_phyrom_version_num" => v = s.c[22],
                    "phy_get_rf_cal_version" => v = s.c[3],
                    "get_iq_value" => {
                        for i in 0..2 {
                            s.put(
                                args[0] + i,
                                1,
                                ((args[1] >> (i * 8)) ^ (args[2] * 0x51)) as u32 ^ s.c[14],
                            );
                        }
                    }
                    _ => {}
                }
                s.mutate();
                s.event(6, &[id, v]);
                v
            } else {
                assert!(
                    (0x71000000..0x71400000).contains(&target),
                    "unknown callback {target:x}"
                );
                let offset = (target - 0x71000000) % 0x1000;
                let (_, n) = SLOTS
                    .iter()
                    .find(|(o, _)| *o == offset)
                    .unwrap_or_else(|| panic!("slot {offset:x}"));
                assert_eq!(args.len(), *n);
                if offset == if S3 { 0x1cc } else { 0x1f0 } {
                    s.snapshot(args[0], 8);
                }
                let mut row = vec![target as u32];
                row.extend(args.iter().map(|v| *v as u32));
                s.event(9, &row);
                let mut v = 0;
                if offset == if S3 { 0x98 } else { 0xa4 } {
                    v = s.get(args[0], 4);
                } else if offset == if S3 { 0xec } else { 0x100 } {
                    v = if s.c[26] != 0 {
                        s.c[14].wrapping_add(s.calls.wrapping_mul(s.c[15]))
                    } else {
                        (args[0] as i32).wrapping_abs() as u32
                    };
                } else if offset == if S3 { 0x160 } else { 0x184 } {
                    v = s.c[14].wrapping_add(s.calls.wrapping_mul(s.c[15]));
                }
                s.mutate();
                s.event(10, &[target as u32, v]);
                v
            }
        })
    }
}
fn arguments(c: &[u32; 48]) -> Vec<usize> {
    let mut input = 0x300000;
    let data = 0x310000;
    let mut reference = 0x320000;
    match c[20] {
        1 => input = data,
        2 => input = 0x200000 + 240,
        3 => reference = data + 300,
        _ => {}
    }
    if c[0] == 11 && c[1] != 0 {
        input = 0;
    }
    match c[0] {
        0 | 1 | 9 | 10 | 12 | 14 | 15 | 16 | 17 => vec![],
        2 | 13 => vec![input],
        3 => vec![data, c[3] as usize],
        4 => vec![data, c[2] as usize],
        5 | 7 => vec![data],
        6 => vec![data, reference, c[2] as usize],
        8 => vec![c[2] as usize, data, input, c[3] as usize],
        11 => vec![input, data, c[2] as usize],
        _ => panic!("kind"),
    }
}
fn main() {
    let raw = fs::read(std::env::args().nth(1).expect("case stream")).unwrap();
    assert_eq!(raw.len() % 4, 0);
    let words: Vec<u32> = raw
        .chunks_exact(4)
        .map(|b| u32::from_le_bytes(b.try_into().unwrap()))
        .collect();
    let mut at = 0;
    let mut count = 0;
    while at < words.len() {
        let c: [u32; 48] = words[at..at + 48].try_into().unwrap();
        at += 48;
        let expected = words[at];
        let length = words[at + 1] as usize;
        at += 2;
        let expected_trace = &words[at..at + length];
        at += length;
        STATE.with(|s| *s.borrow_mut() = Some(State::new(c)));
        let value = unsafe { production::dispatch::<Mock>(c[0], &arguments(&c)) };
        state(|s| {
            let first = s
                .trace
                .iter()
                .zip(expected_trace)
                .position(|(a, b)| a != b)
                .unwrap_or(s.trace.len().min(expected_trace.len()));
            if value != expected || s.trace != expected_trace {
                let start = first / 16 * 16;
                let end = (start + 48).min(s.trace.len());
                let other = (start + 48).min(expected_trace.len());
                panic!(
                    "case {count} {c:?}; value {value}/{expected}; words {}/{}; at {first}: actual {:?}; expected {:?}",
                    s.trace.len(),
                    expected_trace.len(),
                    &s.trace[start.min(end)..end],
                    &expected_trace[start.min(other)..other]
                );
            }
        });
        count += 1;
    }
    println!("passed {count} initialization instruction-oracle cases");
}
