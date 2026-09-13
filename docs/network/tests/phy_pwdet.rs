#![allow(dead_code)]
use std::{cell::RefCell, collections::BTreeMap, fs, mem::MaybeUninit};
#[path = "../../../esp-wifi-hal/src/phy_pwdet.rs"]
mod production;
#[derive(Debug)]
struct BoundaryStop(u32);
struct State {
    case: [u32; 16],
    memory: BTreeMap<usize, u16>,
    mmio: BTreeMap<usize, u32>,
    generation: u32,
    calls: u32,
    fills: u32,
    converts: u32,
    polls: u32,
    trace: Vec<u32>,
    limit: usize,
}
impl State {
    fn new(c: [u32; 16]) -> Self {
        Self {
            case: c,
            memory: BTreeMap::from([
                (0x2000da, c[2] as u16),
                (0x2000dc, c[3] as u16),
                (0x300000, 0xa55a),
                (0x300002, 0xa55a),
            ]),
            mmio: [0x60006040, 0x6000e050, 0x6000e05c]
                .into_iter()
                .enumerate()
                .map(|(i, a)| (a, c[12] ^ (i as u32).wrapping_mul(0x13579bdf)))
                .collect(),
            generation: 0,
            calls: 0,
            fills: 0,
            converts: 0,
            polls: 0,
            trace: vec![],
            limit: if c[0] == 5 && cfg!(esp32c3) && c[1] > 255 {
                6000
            } else if c[13] == 0 {
                96
            } else {
                100000
            },
        }
    }
    fn event(&mut self, kind: u32, args: &[u32]) {
        assert!(args.len() <= 7);
        if self.trace.len() / 8 >= self.limit {
            std::panic::panic_any(BoundaryStop(2));
        }
        self.trace.push(kind);
        self.trace.extend_from_slice(args);
        self.trace.extend(std::iter::repeat_n(0, 7 - args.len()));
    }
    fn mutate(&mut self) {
        let bit = 1 << (self.calls % 32);
        if self.case[9] & bit != 0 {
            self.generation += 1;
        }
        if self.case[10] & bit != 0 {
            *self.memory.get_mut(&0x2000da).unwrap() ^= 0x1357;
            let value = self.memory.get_mut(&0x2000dc).unwrap();
            *value = value.wrapping_add(0x2468);
        }
        self.calls += 1;
    }
    fn check_target(&self, target: usize, offset: usize) {
        assert!((0x71000000..0x72000000).contains(&target));
        assert_eq!((target - 0x71000000) % 0x1000, offset);
        assert!((target - 0x71000000) / 0x1000 <= self.generation as usize);
    }
}
thread_local! {static STATE:RefCell<State>=RefCell::new(State::new([0;16]));}
struct Access;
fn pointer(address: usize, index: u32) -> u32 {
    if address > u32::MAX as usize {
        0x600000 + 2 * index
    } else {
        address as u32
    }
}
const SETUP: usize = if cfg!(esp32c3) { 0x144 } else { 0x120 };
const OUTPUT: usize = if cfg!(esp32c3) { 0x148 } else { 0x124 };
const CONVERT: usize = if cfg!(esp32c3) { 0x118 } else { 0x104 };
impl production::Access for Access {
    unsafe fn param() -> usize {
        0x200000
    }
    unsafe fn read16(address: usize) -> u16 {
        STATE.with_borrow_mut(|s| {
            if let Some(value) = s.memory.get(&address).copied() {
                if address == 0x2000da || address == 0x2000dc {
                    s.event(1, &[(address - 0x200000) as u32, value as u32]);
                }
                value
            } else {
                assert!(address > u32::MAX as usize);
                unsafe { (address as *const u16).read_volatile() }
            }
        })
    }
    unsafe fn write16(address: usize, value: u16) {
        STATE.with_borrow_mut(|s| {
            if s.memory.contains_key(&address) {
                s.event(2, &[address as u32, value as u32]);
                s.memory.insert(address, value);
            } else {
                assert!(address > u32::MAX as usize);
                unsafe { (address as *mut u16).write_volatile(value) }
            }
        });
    }
    unsafe fn read32(address: usize) -> u32 {
        STATE.with_borrow_mut(|s| {
            let mut value = *s.mmio.get(&address).expect("Unknown MMIO read");
            if address == 0x6000e050 {
                let status = (s.case[13] >> (4 * (s.polls % 8))) & 7;
                s.polls += 1;
                value = (value & !(7 << 24)) | (status << 24);
            }
            s.event(7, &[address as u32, value]);
            value
        })
    }
    unsafe fn write32(address: usize, value: u32) {
        STATE.with_borrow_mut(|s| {
            assert!(s.mmio.contains_key(&address));
            s.event(8, &[address as u32, value]);
            s.mmio.insert(address, value);
        });
    }
    unsafe fn table() -> usize {
        STATE.with_borrow_mut(|s| {
            s.event(4, &[s.generation]);
            0x70000000 + s.generation as usize * 0x1000
        })
    }
    unsafe fn slot(table: usize, offset: usize) -> usize {
        STATE.with_borrow_mut(|s| {
            assert!(
                (0x70000000..0x71000000).contains(&table) && (table - 0x70000000) % 0x1000 == 0
            );
            let generation = (table - 0x70000000) / 0x1000;
            assert!(generation <= s.generation as usize);
            assert!([SETUP, OUTPUT, CONVERT].contains(&offset));
            s.event(5, &[offset as u32, generation as u32]);
            0x71000000 + generation * 0x1000 + offset
        })
    }
    unsafe fn setup(target: usize) {
        let compose = STATE.with_borrow_mut(|s| {
            s.check_target(target, SETUP);
            s.event(6, &[target as u32]);
            s.case[8] & 16 != 0
        });
        #[cfg(esp32c3)]
        if compose {
            unsafe { production::pkdet::<Self>() };
        }
        let _ = compose;
        STATE.with_borrow_mut(|s| s.mutate());
    }
    unsafe fn fill(target: usize, output: &mut MaybeUninit<[u16; 8]>) {
        assert_eq!(
            output.as_mut_ptr() as usize % 16,
            0,
            "Native-sized sample buffer must keep stack alignment"
        );
        STATE.with_borrow_mut(|s| {
            s.check_target(target, OUTPUT);
            s.event(6, &[target as u32, 0x600000]);
            let mut values = [0u16; 8];
            for (i, value) in values.iter_mut().enumerate() {
                *value = s.case[4]
                    .wrapping_add(s.fills.wrapping_mul(s.case[5]))
                    .wrapping_add((i as u32).wrapping_sub(1).wrapping_mul(0x1357))
                    as u16;
                s.event(10, &[(i * 2) as u32, *value as u32]);
            }
            output.write(values);
            s.fills += 1;
            s.mutate();
        });
    }
    unsafe fn convert(target: usize, value: i32, selector: u32) -> u32 {
        STATE.with_borrow_mut(|s| {
            s.check_target(target, CONVERT);
            assert_eq!(selector, 3);
            s.event(6, &[target as u32, value as u32, selector]);
            let result = if s.converts % 2 == 0 {
                s.case[6]
            } else {
                s.case[7]
            };
            s.converts += 1;
            s.mutate();
            result
        })
    }
    unsafe fn delay(us: u32) {
        STATE.with_borrow_mut(|s| {
            assert!([1, 2, 10].contains(&us));
            s.event(11, &[us]);
        });
    }
    unsafe fn tone() {
        let compose = STATE.with_borrow_mut(|s| {
            s.event(9, &[2]);
            s.case[8] & 1 != 0
        });
        if compose {
            unsafe { production::tone::<Self>() };
        }
    }
    unsafe fn samples(count: u32) -> u32 {
        let (compose, value) = STATE.with_borrow_mut(|s| {
            s.event(9, &[5, count]);
            (s.case[8] & 2 != 0, s.case[4])
        });
        if compose {
            unsafe { production::samples::<Self>(count) }
        } else {
            value
        }
    }
    unsafe fn reference(input: u32, signal: usize, reference: usize) {
        let (compose, left, right) = STATE.with_borrow_mut(|s| {
            s.event(9, &[1, input, pointer(signal, 0), pointer(reference, 1)]);
            (s.case[8] & 4 != 0, s.case[14] as u16, s.case[15] as u16)
        });
        unsafe {
            if compose {
                production::reference::<Self>(input, signal, reference)
            } else {
                Self::write16(signal, left);
                Self::write16(reference, right);
            }
        }
    }
    unsafe fn fm(signal: usize, reference: usize) -> u32 {
        let (compose, left, right) = STATE.with_borrow_mut(|s| {
            s.event(9, &[6, pointer(signal, 0), pointer(reference, 1)]);
            (s.case[8] & 8 != 0, s.case[14] as u16, s.case[15] as u16)
        });
        unsafe {
            if compose {
                production::fm::<Self>(signal, reference)
            } else {
                Self::write16(signal, left);
                Self::write16(reference, right);
                0
            }
        }
    }
    unsafe fn divide_unsigned(numerator: u32, denominator: u32) -> u32 {
        if denominator == 0 {
            if cfg!(esp32s3) {
                std::panic::panic_any(BoundaryStop(1));
            } else {
                u32::MAX
            }
        } else {
            numerator / denominator
        }
    }
}
#[test]
fn original_instruction_boundaries() {
    let previous = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        if !info.payload().is::<BoundaryStop>() {
            previous(info);
        }
    }));
    let raw = fs::read(std::env::var("PHY_PWDET_CASES").expect("oracle corpus")).unwrap();
    assert_eq!(raw.len() % 4, 0);
    let mut words = raw
        .chunks_exact(4)
        .map(|b| u32::from_le_bytes(b.try_into().unwrap()));
    let mut count = 0;
    while let Some(op) = words.next() {
        let mut case = [0; 16];
        case[0] = op;
        for v in &mut case[1..] {
            *v = words.next().unwrap();
        }
        let expected_status = words.next().unwrap();
        let expected = words.next().unwrap();
        let events = words.next().unwrap();
        let expected_trace: Vec<_> = (0..events * 8).map(|_| words.next().unwrap()).collect();
        STATE.with_borrow_mut(|s| *s = State::new(case));
        let locations = [0x300000, 0x300002, 0x2000da, 0x2000dc];
        let signal = locations[(case[11] % 4) as usize];
        let reference = locations[(case[11] / 4) as usize];
        let actual = std::panic::catch_unwind(|| unsafe {
            match op {
                0 => {
                    production::power();
                    0
                }
                1 => {
                    production::reference::<Access>(case[1], signal, reference);
                    0
                }
                2 => {
                    production::tone::<Access>();
                    0
                }
                #[cfg(esp32c3)]
                3 => {
                    production::pkdet::<Access>();
                    0
                }
                4 => production::read_code::<Access>(),
                5 => production::samples::<Access>(case[1]),
                6 => production::fm::<Access>(signal, reference),
                7 => production::linear::<Access>() as u32,
                8 => production::db::<Access>(case[1]) as u32,
                _ => panic!("Unknown operation"),
            }
        });
        let (status, value) = match actual {
            Ok(value) => (0, value),
            Err(payload) => match payload.downcast::<BoundaryStop>() {
                Ok(stop) => (stop.0, 0),
                Err(other) => std::panic::resume_unwind(other),
            },
        };
        assert_eq!(
            (status, value),
            (expected_status, expected),
            "case {count}: {case:?}"
        );
        STATE.with_borrow(|s| assert_eq!(s.trace, expected_trace, "case {count}: {case:?}"));
        count += 1;
    }
    assert_eq!(
        count,
        std::env::var("PHY_PWDET_CASE_COUNT")
            .unwrap()
            .parse::<usize>()
            .unwrap()
    );
    println!("{count} original-instruction cases passed");
}
