#![allow(dead_code)]
use std::{cell::RefCell, fs};
#[path = "../../../esp-wifi-hal/src/phy_feature.rs"]
mod production;
struct State {
    case: [u32; 16],
    parameters: [u8; 848],
    registers: [u32; 2],
    generation: u32,
    calls: u32,
    trace: Vec<u32>,
}
impl State {
    fn new(case: [u32; 16]) -> Self {
        let mut parameters = [0xa5; 848];
        for i in 0..3 {
            parameters[0x166 + i] = case[3 + i] as u8;
        }
        parameters[0x1f2] = case[6] as u8;
        Self {
            parameters,
            registers: [case[7], case[8]],
            case,
            generation: 0,
            calls: 0,
            trace: Vec::new(),
        }
    }
    fn event(&mut self, kind: u32, args: &[u32]) {
        assert!(args.len() <= 7);
        self.trace.push(kind);
        self.trace.extend_from_slice(args);
        self.trace.extend(std::iter::repeat_n(0, 7 - args.len()));
    }
}
thread_local! { static STATE:RefCell<State>=RefCell::new(State::new([0;16])); }
struct Access;
impl production::Access for Access {
    unsafe fn parameter(offset: usize) -> u8 {
        STATE.with_borrow_mut(|s| {
            assert!([0x166, 0x167, 0x168, 0x1f2].contains(&offset));
            let v = s.parameters[offset];
            s.event(1, &[1, offset as u32, v as u32]);
            v
        })
    }
    unsafe fn set_parameter(offset: usize, value: u8) {
        STATE.with_borrow_mut(|s| {
            assert!([0x98, 0xef, 0xf0].contains(&offset));
            s.parameters[offset] = value;
            s.event(2, &[1, offset as u32, value as u32]);
            if [0x98, 0xef].contains(&offset) && s.case[11] & 1 != 0 {
                s.generation += 1;
                s.parameters[0x1f2] ^= s.case[13] as u8;
            }
        });
    }
    unsafe fn table() -> usize {
        STATE.with_borrow_mut(|s| {
            s.event(4, &[s.generation]);
            0x70000000 + s.generation as usize * 0x1000
        })
    }
    unsafe fn callback(table: usize, offset: usize) -> usize {
        STATE.with_borrow_mut(|s| {
            assert!(table >= 0x70000000 && (table - 0x70000000) % 0x1000 == 0);
            let generation = (table - 0x70000000) / 0x1000;
            assert!(generation <= s.generation as usize);
            assert_eq!(
                offset,
                if cfg!(esp32s3) && s.case[0] == 2 {
                    0x264
                } else if cfg!(esp32s3) {
                    0x190
                } else {
                    0x1b4
                }
            );
            s.event(5, &[offset as u32, generation as u32]);
            0x71000000 + generation * 0x1000 + offset
        })
    }
    unsafe fn call(target: usize, args: [u32; 4]) {
        STATE.with_borrow_mut(|s| {
            assert!((0x71000000..0x71020000).contains(&target));
            assert!(((target - 0x71000000) / 0x1000) <= s.generation as usize);
            s.event(6, &[target as u32, args[0], args[1], args[2], args[3]]);
            if s.case[9] & (1 << s.calls) != 0 {
                s.generation += 1;
            }
            if s.case[10] & (1 << s.calls) != 0 {
                s.parameters[0x167] = s.parameters[0x167].wrapping_add(s.case[13] as u8);
                s.parameters[0x168] ^= s.case[13] as u8;
            }
            s.calls += 1;
        });
    }
    unsafe fn gain(channel: u32) {
        STATE.with_borrow_mut(|s| s.event(9, &[2, channel, 0]));
    }
    unsafe fn read_register(address: usize) -> u32 {
        STATE.with_borrow_mut(|s| {
            let index = match address {
                0x6002600c => 0,
                0x6001c030 => 1,
                _ => panic!("Unknown MMIO"),
            };
            let v = s.registers[index];
            s.event(7, &[address as u32, v]);
            v
        })
    }
    unsafe fn write_register(address: usize, value: u32) {
        STATE.with_borrow_mut(|s| {
            let index = match address {
                0x6002600c => 0,
                0x6001c030 => 1,
                _ => panic!("Unknown MMIO"),
            };
            s.registers[index] = value;
            s.event(8, &[address as u32, value]);
            if s.case[11] & 2 != 0 {
                s.generation += 1;
            }
            if s.case[11] & 4 != 0 {
                s.parameters[0x166] ^= s.case[13] as u8;
            }
        });
    }
    unsafe fn backup(kind: u32, mode: u32, buffer: usize) -> u32 {
        STATE.with_borrow_mut(|s| {
            assert!(kind < 2);
            s.event(9, &[kind, mode, buffer as u32]);
            s.case[12]
        })
    }
}
#[test]
fn original_instruction_boundaries() {
    let raw = fs::read(std::env::var("PHY_FEATURE_CASES").expect("oracle corpus")).unwrap();
    assert_eq!(raw.len() % 4, 0);
    let mut words = raw
        .chunks_exact(4)
        .map(|b| u32::from_le_bytes(b.try_into().unwrap()));
    let mut count = 0;
    while let Some(op) = words.next() {
        let mut case = [0; 16];
        case[0] = op;
        for value in &mut case[1..] {
            *value = words.next().unwrap();
        }
        let expected = words.next().unwrap();
        let events = words.next().unwrap();
        let trace: Vec<_> = (0..events * 8).map(|_| words.next().unwrap()).collect();
        STATE.with_borrow_mut(|s| *s = State::new(case));
        let actual = unsafe {
            match op {
                0 => production::backup::<Access>(0, case[1], case[2] as usize),
                1 => {
                    production::backup::<Access>(1, case[1], case[2] as usize);
                    0
                }
                2 => {
                    production::power::<Access>(case[1]);
                    0
                }
                3 => {
                    production::mode::<Access>(case[1], case[2]);
                    0
                }
                _ => panic!("Unknown operation"),
            }
        };
        assert_eq!(actual, expected, "case {count}: {case:?}");
        STATE.with_borrow(|s| assert_eq!(s.trace, trace, "case {count}: {case:?}"));
        count += 1;
    }
    assert_eq!(
        count,
        std::env::var("PHY_FEATURE_CASE_COUNT")
            .unwrap()
            .parse::<usize>()
            .unwrap()
    );
    println!("{count} original-instruction cases passed");
}
