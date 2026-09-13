#![allow(dead_code)]
use std::{cell::RefCell, fs};
#[path = "../../../esp-wifi-hal/src/phy_debug.rs"]
mod production;
struct State {
    case: [u32; 16],
    generation: u32,
    calls: u32,
    samples: u32,
    trace: Vec<u32>,
}
impl State {
    fn new(case: [u32; 16]) -> Self {
        Self {
            case,
            generation: 0,
            calls: 0,
            samples: 0,
            trace: Vec::new(),
        }
    }
    fn event(&mut self, kind: u32, args: &[u32]) {
        assert!(args.len() <= 7);
        self.trace.push(kind);
        self.trace.extend_from_slice(args);
        self.trace.extend(std::iter::repeat_n(0, 7 - args.len()));
    }
    fn call(&mut self, target: usize, args: &[u32], sample: bool) -> u32 {
        assert!((0x71000000..0x71020000).contains(&target));
        assert!(((target - 0x71000000) / 0x1000) <= self.generation as usize);
        let mut event = vec![target as u32];
        event.extend_from_slice(args);
        self.event(6, &event);
        let result = if sample {
            let result = if self.case[0] == 1 || (self.case[6] != 0 && self.samples == 0) {
                self.case[3]
            } else {
                self.case[4]
            };
            self.samples += 1;
            result
        } else {
            self.case[8] ^ 0xdeadbeef
        };
        if self.case[5] & (1 << self.calls) != 0 {
            self.generation += 1;
        }
        self.calls += 1;
        assert!(self.calls <= 12);
        result
    }
}
thread_local! {static STATE:RefCell<State>=RefCell::new(State::new([0;16]));}
struct Access;
impl production::Access for Access {
    unsafe fn table() -> usize {
        STATE.with_borrow_mut(|s| {
            s.event(4, &[s.generation]);
            0x70000000 + s.generation as usize * 0x1000
        })
    }
    unsafe fn slot(table: usize, offset: usize) -> usize {
        STATE.with_borrow_mut(|s| {
            assert!(table >= 0x70000000 && (table - 0x70000000) % 0x1000 == 0);
            let generation = (table - 0x70000000) / 0x1000;
            assert!(generation <= s.generation as usize);
            assert!(
                (if cfg!(esp32s3) {
                    [0x198, 0x12c, 0x1b0, 0x1a8, 0x1b4]
                } else {
                    [0x1bc, 0x150, 0x1d4, 0x1cc, 0x1d8]
                })
                .contains(&offset)
            );
            s.event(5, &[offset as u32, generation as u32]);
            0x71000000 + generation * 0x1000 + offset
        })
    }
    unsafe fn write_iq(destination: usize, offset: usize, value: i8) {
        assert_eq!(destination, 0x200003);
        assert!(offset < 2);
        STATE.with_borrow_mut(|s| {
            s.event(1, &[destination as u32, offset as u32, value as u8 as u32])
        });
    }
    unsafe fn write_mask(target: usize, args: [u32; 6]) {
        STATE.with_borrow_mut(|s| {
            s.call(target, &args, false);
        });
    }
    unsafe fn sample(target: usize, selector: u32) -> u32 {
        STATE.with_borrow_mut(|s| s.call(target, &[selector], true))
    }
    unsafe fn setup(target: usize) {
        STATE.with_borrow_mut(|s| {
            s.call(target, &[], false);
        });
    }
    unsafe fn mode(target: usize, args: [u32; 3]) {
        STATE.with_borrow_mut(|s| {
            s.call(target, &args, false);
        });
    }
    unsafe fn bias() -> u32 {
        let (composed, value) = STATE.with_borrow_mut(|s| {
            s.event(9, &[]);
            if s.case[7] != 0 {
                s.generation += 1;
            }
            (s.case[6] != 0, s.case[3])
        });
        if composed {
            unsafe { production::bias::<Self>() }
        } else {
            value
        }
    }
}
#[test]
fn original_instruction_boundaries() {
    let raw = fs::read(std::env::var("PHY_DEBUG_CASES").expect("oracle corpus")).unwrap();
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
                0 => {
                    production::iq::<Access>(0x200003, case[1], case[2]);
                    0
                }
                1 => production::bias::<Access>(),
                2 => production::voltage::<Access>(),
                _ => panic!("Unknown operation"),
            }
        };
        assert_eq!(actual, expected, "case {count}: {case:?}");
        STATE.with_borrow(|s| assert_eq!(s.trace, trace, "case {count}: {case:?}"));
        count += 1;
    }
    assert_eq!(
        count,
        std::env::var("PHY_DEBUG_CASE_COUNT")
            .unwrap()
            .parse::<usize>()
            .unwrap()
    );
    println!("{count} original-instruction cases passed");
}
