#![allow(dead_code)]
use std::{cell::RefCell, collections::BTreeMap, fs};
#[path = "../../../esp-wifi-hal/src/phy_rfpll.rs"]
mod production;
const S3: bool = cfg!(esp32s3);
fn fields() -> Vec<(usize, usize)> {
    let mut v = vec![];
    for o in [
        0xe6,
        0xef,
        0xf0,
        0xf1,
        0xf3,
        0x1f2,
        0x1f3,
        0x1f4,
        0x1f6,
        0x11a,
        0x11e,
        0x11f,
        if S3 { 0x2a8 } else { 0x325 },
    ] {
        v.push((o, 1));
    }
    for o in [0xe0, 0x11c, 0x118, if S3 { 0x2aa } else { 0x326 }] {
        v.push((o, 2));
    }
    v.push((0x120, 4));
    v
}
fn arity(slot: usize) -> usize {
    if S3 {
        match slot {
            0x188 => 3,
            0x190 => 4,
            0x194 => 5,
            0x198 => 6,
            0x28 => 3,
            0x20c | 0x1d4 | 0x164 | 0x6c | 0x24c => 1,
            0x160 | 8 | 12 => 0,
            0x264 => 2,
            _ => panic!("unknown slot {slot:x}"),
        }
    } else {
        match slot {
            0x1ac => 3,
            0x1b4 => 4,
            0x1b8 => 5,
            0x1bc => 6,
            0x28 => 3,
            0x1f8 | 0x188 | 0x78 => 1,
            0x184 | 8 | 12 => 0,
            0x60 => 7,
            _ => panic!("unknown slot {slot:x}"),
        }
    }
}
struct State {
    case: [u32; 48],
    memory: BTreeMap<usize, u8>,
    trace: Vec<u32>,
    generation: u32,
    calls: u32,
    clamps: usize,
    statuses: usize,
    polls: u32,
    mmreads: u32,
}
impl State {
    fn put(&mut self, a: usize, w: usize, v: u32) {
        for i in 0..w {
            self.memory.insert(a + i, (v >> (8 * i)) as u8);
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
            case: c,
            memory: BTreeMap::new(),
            trace: vec![],
            generation: 0,
            calls: 0,
            clamps: 0,
            statuses: 0,
            polls: 0,
            mmreads: 0,
        };
        for (o, i, shift) in [
            (0xe0, 24, 0),
            (if S3 { 0x2aa } else { 0x326 }, 24, 16),
            (0x11c, 28, 0),
            (0x118, 28, 16),
        ] {
            s.put(0x200000 + o, 2, c[i] >> shift);
        }
        for (o, i, shift) in [
            (if S3 { 0x2a8 } else { 0x325 }, 25, 0),
            (0xef, 25, 8),
            (0xe6, 25, 16),
            (0x1f4, 25, 24),
            (0x1f2, 26, 0),
            (0xf3, 26, 8),
            (0xf0, 26, 16),
            (0xf1, 26, 24),
            (0x1f6, 27, 0),
            (0x11a, 27, 8),
            (0x11e, 27, 16),
            (0x11f, 27, 24),
        ] {
            s.put(0x200000 + o, 1, c[i] >> shift);
        }
        s.put(0x2001f3, 1, 0);
        s.put(0x200120, 4, c[29]);
        for i in 0..16 {
            s.put(0x300000 + i, 1, c[30 + i / 4 % 2] >> (8 * (i % 4)));
        }
        for (i, a) in [0x6000e0c4, 0x6000e0c0, 0x6000e148, 0x6001c130]
            .into_iter()
            .enumerate()
        {
            s.put(a, 4, c[32 + i]);
        }
        if c[37] != 0 {
            let p = 0x200000 + if c[37] == 1 { 0xe0 } else { 0x11e };
            for i in 0..3 {
                if !s.memory.contains_key(&(p + i)) {
                    s.put(p + i, 1, c[30] >> (i * 8));
                }
            }
        }
        s
    }
    fn event(&mut self, kind: u32, args: &[u32]) {
        assert!(args.len() <= 11 && self.trace.len() < 12 * 4096);
        self.trace.push(kind);
        self.trace.extend_from_slice(args);
        self.trace.extend(std::iter::repeat_n(0, 11 - args.len()));
    }
    fn mutate(&mut self) {
        assert!(self.calls < 1024);
        let mask = 1 << (self.calls % 32);
        if self.case[19] & mask != 0 {
            self.generation += 1;
        }
        if self.case[20] & mask != 0 {
            for (o, w) in fields() {
                self.put(
                    0x200000 + o,
                    w,
                    self.get(0x200000 + o, w) ^ self.case[22].wrapping_add(o as u32 * 17),
                );
            }
        }
        if self.case[21] & mask != 0 {
            for i in 0..3 {
                self.put(
                    0x300000 + i,
                    1,
                    self.get(0x300000 + i, 1) ^ self.case[22].wrapping_add(i as u32 * 17),
                );
            }
        }
        self.calls += 1;
    }
    fn read(&mut self, a: usize, w: usize) -> u32 {
        let mut v = self.get(a, w);
        if a >= 0x60000000 {
            assert_eq!(w, 4);
            v ^= self.case[36].wrapping_mul(self.mmreads);
            self.mmreads += 1;
            self.event(7, &[a as u32, v]);
        } else {
            self.event(1, &[a as u32, w as u32, v]);
        }
        v
    }
    fn write(&mut self, a: usize, w: usize, v: u32) {
        let v = if w == 4 { v } else { v & ((1 << (w * 8)) - 1) };
        if a >= 0x60000000 {
            self.event(8, &[a as u32, v]);
        } else {
            self.event(2, &[a as u32, w as u32, v]);
        }
        self.put(a, w, v);
    }
    fn callback(&mut self, t: usize, a: &[u32]) -> Option<u32> {
        assert!((0x71000000..0x71400000).contains(&t));
        let slot = (t - 0x71000000) % 0x1000;
        let gen_id = (t - 0x71000000) / 0x1000;
        assert!(gen_id <= self.generation as usize);
        assert_eq!(arity(slot), a.len());
        let mut args = vec![t as u32];
        args.extend_from_slice(a);
        self.event(6, &args);
        if S3 && slot == 0x20c && self.case[23] & (1 << 5) != 0 {
            return None;
        }
        let v = if slot == 0x28 {
            let v = if self.case[9] != 0 {
                self.case[7 + self.clamps.min(1)]
            } else {
                (a[0] as i32).max(a[2] as i32).min(a[1] as i32) as u32
            };
            self.clamps += 1;
            v
        } else if slot == if S3 { 0x1d4 } else { 0x1f8 } {
            self.case[11]
        } else if slot == if S3 { 0x188 } else { 0x1ac } {
            if a == [98, 1, 5] {
                self.case[5]
            } else {
                assert_eq!(a, [98, 1, 12]);
                let code = if self.statuses < 32 {
                    (self.case[14 + self.statuses / 16] >> (2 * (self.statuses % 16))) & 3
                } else {
                    self.case[16] & 3
                };
                self.statuses += 1;
                (self.case[13] & !12) | (code << 2)
            }
        } else if slot == if S3 { 0x194 } else { 0x1b8 } {
            if a == [98, 1, 7, 2, 2] {
                self.case[6]
            } else {
                assert_eq!(a, [98, 1, 7, 1, 1]);
                let v = if self.polls < self.case[17] {
                    0
                } else {
                    self.case[18]
                };
                self.polls += 1;
                v
            }
        } else {
            self.case[12]
        };
        self.mutate();
        Some(v)
    }
}
thread_local! {static STATE:RefCell<State>=RefCell::new(State::new([0;48]));}
struct Access;
impl production::Access for Access {
    unsafe fn param() -> usize {
        0x200000
    }
    unsafe fn read(a: usize, w: usize) -> u32 {
        STATE.with_borrow_mut(|s| s.read(a, w))
    }
    unsafe fn write(a: usize, w: usize, v: u32) {
        STATE.with_borrow_mut(|s| s.write(a, w, v));
    }
    unsafe fn table() -> usize {
        STATE.with_borrow_mut(|s| {
            s.event(4, &[s.generation]);
            0x70000000 + s.generation as usize * 0x1000
        })
    }
    unsafe fn slot(t: usize, o: usize) -> usize {
        STATE.with_borrow_mut(|s| {
            assert!((0x70000000..0x70400000).contains(&t));
            let gen_id = (t - 0x70000000) / 0x1000;
            assert!(gen_id <= s.generation as usize);
            arity(o);
            s.event(5, &[o as u32, gen_id as u32]);
            0x71000000 + gen_id * 0x1000 + o
        })
    }
    unsafe fn read_call<const N: usize>(t: usize, a: [u32; N]) -> u32 {
        unsafe {
            match STATE.with_borrow_mut(|s| s.callback(t, &a)) {
                Some(v) => v,
                None => {
                    production::write_cap::<Access>(a[0]);
                    0
                }
            }
        }
    }
    unsafe fn write_call<const N: usize>(t: usize, a: [u32; N]) {
        unsafe {
            Self::read_call(t, a);
        }
    }
    unsafe fn external<const N: usize>(kind: u32, a: [u32; N]) {
        STATE.with_borrow_mut(|s| {
            assert_eq!(N, [1, 1, 3, 8, 1, 2, 1, 0, 1, 2, 2][kind as usize]);
            if kind == 3 {
                let bytes = (0..if S3 { 1 } else { 9 })
                    .map(|i| s.get(a[2] as usize + i, 1))
                    .collect::<Vec<_>>();
                s.event(13, &bytes);
            }
            let mut args = vec![kind];
            args.extend_from_slice(&a);
            s.event(10, &args);
            s.mutate();
        });
    }
    unsafe fn internal<const N: usize>(kind: u32, a: [u32; N]) -> u32 {
        unsafe {
            let mut args = [0; 4];
            args[..N].copy_from_slice(&a);
            let nested = STATE.with_borrow_mut(|s| {
                let mut args = vec![kind];
                args.extend_from_slice(&a);
                s.event(9, &args);
                s.case[23] & (1 << kind) != 0
            });
            if nested {
                execute(kind, args)
            } else {
                STATE.with_borrow_mut(|s| {
                    if (kind == 3 || kind == 9) && s.case[38] != 0 {
                        for i in 0..3 {
                            s.put(a[3] as usize + i, 1, s.case[30] >> (8 * i));
                        }
                    }
                    s.mutate();
                    if kind == 6 { s.case[10] } else { s.case[12] }
                })
            }
        }
    }
    unsafe fn print(kind: u32, a: [u32; 6]) {
        STATE.with_borrow_mut(|s| {
            let mut args = vec![kind];
            if kind == 1 {
                args.extend_from_slice(&a);
            }
            s.event(12, &args);
            s.mutate();
        });
    }
    unsafe fn scratch<F: FnOnce(usize) -> u32>(kind: u32, f: F) -> u32 {
        f(if kind == 1 { 0x310000 } else { 0x300000 })
    }
    unsafe fn init_scratch(a: usize, bytes: &[u8]) {
        STATE.with_borrow_mut(|s| {
            for (i, v) in bytes.iter().enumerate() {
                s.put(a + i, 1, (*v).into());
            }
        });
    }
}
unsafe fn execute(kind: u32, a: [u32; 4]) -> u32 {
    unsafe {
        match kind {
            0 => {
                production::restart::<Access>();
                0
            }
            1 => {
                production::sdm::<Access>(a[0] as usize);
                0
            }
            2 => {
                production::wait::<Access>();
                0
            }
            3 => {
                production::frequency::<Access>(a[0], a[1], a[2], a[3] as usize);
                0
            }
            4 => {
                production::correct_offset::<Access>(a[0], a[1], a[2] as usize);
                0
            }
            5 => {
                production::write_cap::<Access>(a[0]);
                0
            }
            6 => production::read_cap::<Access>(),
            7 => production::correct_cap::<Access>(a[0], a[1]),
            8 => production::init_cap::<Access>(),
            9 => {
                production::set::<Access>(a[0], a[1], a[2], a[3] as usize);
                0
            }
            10 => {
                production::set_offset::<Access>(a[0], a[1], a[2]);
                0
            }
            11 => production::set_channel::<Access>(a[0], a[1], a[2]),
            12 => {
                production::misc::<Access>(a[0]);
                0
            }
            13 => {
                production::channel::<Access>(a[0], a[1]);
                0
            }
            14 => {
                production::channel_offset::<Access>(a[0]);
                0
            }
            15 => {
                production::channel_analog::<Access>(a[0]);
                0
            }
            #[cfg(esp32s3)]
            16 => {
                production::phy_frequency::<Access>(a[0], a[1]);
                0
            }
            #[cfg(esp32s3)]
            17 => 0,
            _ => panic!("unknown operation {kind}"),
        }
    }
}
#[test]
fn original_instruction_cases() {
    let bytes = fs::read(std::env::var("PHY_RFPLL_CASES").unwrap()).unwrap();
    let words = bytes
        .chunks_exact(4)
        .map(|b| u32::from_le_bytes(b.try_into().unwrap()))
        .collect::<Vec<_>>();
    assert_eq!(bytes.len() % 4, 0);
    let mut pos = 0;
    let mut count = 0;
    while pos < words.len() {
        let c: [u32; 48] = words[pos..pos + 48].try_into().unwrap();
        let expected = words[pos + 48];
        let len = words[pos + 49] as usize * 12;
        let trace = &words[pos + 50..pos + 50 + len];
        let mut a: [u32; 4] = c[1..5].try_into().unwrap();
        let index = match c[0] {
            1 => Some(0),
            3 | 9 => Some(3),
            4 => Some(2),
            _ => None,
        };
        if let Some(i) = index {
            a[i] = if c[37] == 0 {
                0x300000
            } else {
                0x200000 + if c[37] == 1 { 0xe0 } else { 0x11e }
            };
        }
        STATE.set(State::new(c));
        let result = unsafe { execute(c[0], a) };
        STATE.with_borrow(|s|{if s.trace!=trace{let mismatch=s.trace.chunks(12).zip(trace.chunks(12)).position(|(a,b)|a!=b).unwrap_or(s.trace.len().min(trace.len())/12);panic!("case {count} op{} words={c:x?} mismatch event{mismatch}: actual={:x?} expected={:x?} lengths {}/{}",c[0],s.trace.chunks(12).nth(mismatch),trace.chunks(12).nth(mismatch),s.trace.len()/12,trace.len()/12);}assert_eq!(result,expected,"case {count} op{}",c[0]);});
        pos += 50 + len;
        count += 1;
    }
    if let Ok(v) = std::env::var("PHY_RFPLL_CASE_COUNT") {
        assert_eq!(count, v.parse::<usize>().unwrap());
    }
    println!("{count} original-instruction cases passed");
}
