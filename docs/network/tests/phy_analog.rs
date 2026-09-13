#![allow(dead_code)]
use std::{cell::RefCell, collections::BTreeMap, fs};
#[path = "../../../esp-wifi-hal/src/phy_analog.rs"]
mod production;
struct State {
    case: [u32; 16],
    memory: BTreeMap<usize, u8>,
    trace: Vec<u32>,
    generation: u32,
    calls: u32,
    soft_calls: u32,
}
const MODE: usize = if cfg!(esp32c3) { 0x322 } else { 0x2a5 };
const WRITE: usize = if cfg!(esp32c3) { 0x1bc } else { 0x198 };
impl State {
    fn put(&mut self, address: usize, width: usize, value: u32) {
        for i in 0..width {
            self.memory.insert(address + i, (value >> (8 * i)) as u8);
        }
    }
    fn get(&self, address: usize, width: usize) -> u32 {
        (0..width)
            .map(|i| {
                u32::from(
                    *self
                        .memory
                        .get(&(address + i))
                        .expect("uninitialized memory"),
                ) << (8 * i)
            })
            .fold(0, |a, b| a | b)
    }
    fn new(case: [u32; 16]) -> Self {
        let mut s = Self {
            case,
            memory: BTreeMap::new(),
            trace: vec![],
            generation: 0,
            calls: 0,
            soft_calls: 0,
        };
        s.put(0x200120, 4, case[3]);
        s.put(0x200000 + MODE, 1, case[4]);
        s.put(0x2000f3, 1, case[1]);
        s.put(0x300000, 2, case[5]);
        s.put(0x300002, 2, case[6]);
        s
    }
    fn event(&mut self, kind: u32, args: &[u32]) {
        assert!(args.len() <= 7);
        self.trace.push(kind);
        self.trace.extend_from_slice(args);
        self.trace.extend(std::iter::repeat_n(0, 7 - args.len()));
    }
    fn mutate_state(&mut self) {
        self.put(0x200120, 4, self.get(0x200120, 4) ^ 0x01000000);
        self.put(0x2000f3, 1, self.get(0x2000f3, 1) + 37);
        self.put(0x200000 + MODE, 1, self.get(0x200000 + MODE, 1) ^ 1);
        if cfg!(esp32c3) {
            for a in [0x300000, 0x300002] {
                self.put(a, 2, self.get(a, 2) ^ 0x173);
            }
        }
    }
    fn mutate_callback(&mut self) {
        if self.case[7] & (1 << self.calls) != 0 {
            self.generation += 1;
        }
        if self.case[8] & (1 << self.calls) != 0 {
            self.mutate_state();
        }
        self.calls += 1;
        assert!(self.calls <= 10);
    }
    fn read(&mut self, address: usize, width: usize) -> u32 {
        assert!(
            matches!(
                (address, width),
                (0x200120, 4) | (0x2000f3, 1) | (0x300000, 2) | (0x300002, 2)
            ) || (address == 0x200000 + MODE && width == 1)
        );
        let v = self.get(address, width);
        self.event(1, &[address as u32, width as u32, v]);
        v
    }
    fn write(&mut self, address: usize, width: usize, value: u32) {
        assert!(
            (address == 0x200120 && width == 4)
                || ((0x200166..=0x20016e).contains(&address) && width == 1)
        );
        self.event(2, &[address as u32, width as u32, value]);
        self.put(address, width, value);
    }
    fn target(&self, target: usize, slot: usize) {
        assert!((0x71000000..0x71010000).contains(&target));
        assert_eq!((target - 0x71000000) % 0x1000, slot);
        assert!((target - 0x71000000) / 0x1000 <= self.generation as usize);
    }
}
thread_local! {static STATE:RefCell<State>=RefCell::new(State::new([0;16]));}
struct Access;
impl production::Access for Access {
    unsafe fn param() -> usize {
        0x200000
    }
    #[cfg(esp32c3)]
    unsafe fn divisors() -> [usize; 2] {
        [0x300000, 0x300002]
    }
    unsafe fn read8(a: usize) -> u8 {
        STATE.with_borrow_mut(|s| s.read(a, 1) as u8)
    }
    #[cfg(esp32c3)]
    unsafe fn read16(a: usize) -> u16 {
        STATE.with_borrow_mut(|s| s.read(a, 2) as u16)
    }
    unsafe fn read32(a: usize) -> u32 {
        STATE.with_borrow_mut(|s| s.read(a, 4))
    }
    unsafe fn write8(a: usize, v: u8) {
        STATE.with_borrow_mut(|s| s.write(a, 1, v.into()));
    }
    unsafe fn write32(a: usize, v: u32) {
        STATE.with_borrow_mut(|s| s.write(a, 4, v));
    }
    unsafe fn table() -> usize {
        STATE.with_borrow_mut(|s| {
            s.event(4, &[s.generation]);
            0x70000000 + s.generation as usize * 0x1000
        })
    }
    unsafe fn slot(table: usize, offset: usize) -> usize {
        STATE.with_borrow_mut(|s| {
            assert!((0x70000000..0x70010000).contains(&table));
            assert_eq!((table - 0x70000000) % 0x1000, 0);
            let active = (table - 0x70000000) / 0x1000;
            assert!(active <= s.generation as usize && (offset == WRITE || offset == WRITE - 4));
            s.event(5, &[offset as u32, active as u32]);
            0x71000000 + active * 0x1000 + offset
        })
    }
    unsafe fn masked_write(target: usize, args: [u32; 6]) {
        STATE.with_borrow_mut(|s| {
            s.target(target, WRITE);
            s.event(
                6,
                &[
                    target as u32,
                    args[0],
                    args[1],
                    args[2],
                    args[3],
                    args[4],
                    args[5],
                ],
            );
            s.mutate_callback();
        });
    }
    unsafe fn masked_read(target: usize, args: [u32; 5]) -> u32 {
        STATE.with_borrow_mut(|s| {
            s.target(target, WRITE - 4);
            s.event(
                6,
                &[target as u32, args[0], args[1], args[2], args[3], args[4]],
            );
            let value = s.case[2];
            s.mutate_callback();
            value
        })
    }
    unsafe fn delay(us: u32) {
        STATE.with_borrow_mut(|s| {
            assert_eq!(us, 100);
            s.event(11, &[us]);
        });
    }
    unsafe fn measurement(selector: u32) -> u32 {
        let (compose, value) = STATE.with_borrow_mut(|s| {
            s.event(9, &[selector]);
            if s.case[10] != 0 {
                s.mutate_state();
            }
            (s.case[9] != 0, s.case[2])
        });
        if compose {
            unsafe { production::measurement::<Self>(selector) }
        } else {
            value
        }
    }
    unsafe fn soft_double(kind: u32, left: u64, right: u64) -> u64 {
        STATE.with_borrow_mut(|s| {
            assert!(kind < 4 && s.soft_calls < 7);
            let result = if s.case[12] & (1 << s.soft_calls) != 0 {
                s.case[13] as u64
                    | if kind != 3 {
                        (s.case[14] as u64) << 32
                    } else {
                        0
                    }
            } else {
                match kind {
                    0 => (left as u32 as i32 as f64).to_bits(),
                    1 => (f64::from_bits(left) / f64::from_bits(right)).to_bits(),
                    2 => (f64::from_bits(left) - f64::from_bits(right)).to_bits(),
                    3 => {
                        let v = f64::from_bits(left);
                        assert!(v.is_finite() && (-2147483648.0..2147483648.0).contains(&v));
                        v as i32 as u32 as u64
                    }
                    _ => unreachable!(),
                }
            };
            s.event(
                12,
                &[
                    kind,
                    left as u32,
                    (left >> 32) as u32,
                    right as u32,
                    (right >> 32) as u32,
                    result as u32,
                    (result >> 32) as u32,
                ],
            );
            if s.case[15] & (1 << s.soft_calls) != 0 {
                s.mutate_state();
            }
            s.soft_calls += 1;
            result
        })
    }
}
#[test]
fn original_instruction_boundaries() {
    let raw = fs::read(std::env::var("PHY_ANALOG_CASES").expect("oracle corpus")).unwrap();
    assert_eq!(raw.len() % 4, 0);
    let mut words = raw
        .chunks_exact(4)
        .map(|v| u32::from_le_bytes(v.try_into().unwrap()));
    let mut count = 0;
    while let Some(op) = words.next() {
        let mut case = [0; 16];
        case[0] = op;
        for v in &mut case[1..] {
            *v = words.next().unwrap();
        }
        let expected = words.next().unwrap();
        let events = words.next().unwrap();
        let trace: Vec<_> = (0..events * 8).map(|_| words.next().unwrap()).collect();
        STATE.with_borrow_mut(|s| *s = State::new(case));
        let value = unsafe {
            match op {
                0 => production::measurement::<Access>(case[1]),
                1 => {
                    production::calibrate::<Access>();
                    0
                }
                _ => panic!("unknown operation"),
            }
        };
        assert_eq!(value, expected, "case {count}: {case:?}");
        STATE.with_borrow(|s| assert_eq!(s.trace, trace, "case {count}: {case:?}"));
        count += 1;
    }
    assert_eq!(
        count,
        std::env::var("PHY_ANALOG_CASE_COUNT")
            .unwrap()
            .parse::<usize>()
            .unwrap()
    );
    println!("{count} original-instruction cases passed");
}
