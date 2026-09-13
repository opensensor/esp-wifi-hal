//! Compare the production basic PHY logic with original-instruction effects.
#[path = "../../../esp-wifi-hal/src/phy_basic.rs"]
mod phy_basic;
use std::cell::RefCell;
#[derive(Default)]
struct State {
    case: [u32; 16],
    hosts: [u32; 2],
    remaining: [u32; 2],
    reset: [bool; 2],
    mmio: u32,
    critical_calls: usize,
    trace: Vec<u32>,
}
impl State {
    fn event(&mut self, kind: u32, fields: &[u32]) {
        assert!(fields.len() <= 4);
        let mut event = [0; 5];
        event[0] = kind;
        event[1..1 + fields.len()].copy_from_slice(fields);
        self.trace.extend(event);
    }
}
thread_local! { static STATE: RefCell<State> = RefCell::new(State::default()); }
struct Boundary;
fn critical() {
    STATE.with(|state| {
        let mut s = state.borrow_mut();
        s.event(9, &[0]);
        s.critical_calls += 1;
        assert!(s.critical_calls <= 2);
        if s.critical_calls == 1 {
            s.hosts[0] ^= s.case[11];
            s.hosts[1] ^= s.case[11];
        }
    });
}
impl phy_basic::Access for Boundary {
    unsafe fn enter() {
        critical();
    }
    unsafe fn exit() {
        critical();
    }
    unsafe fn read_register(address: usize) -> u32 {
        STATE.with(|state| {
            let mut s = state.borrow_mut();
            let value = match address {
                0x6000e000 | 0x6000e004 => {
                    let i = (address - 0x6000e000) / 4;
                    if !s.reset[i] {
                        s.hosts[i]
                    } else {
                        let mut value = s.case[6 + i] & !(1 << 25);
                        if s.remaining[i] != 0 {
                            value |= 1 << 25;
                            s.remaining[i] -= 1;
                        }
                        value
                    }
                }
                0x6001c400 => s.mmio,
                _ => panic!("Unknown register"),
            };
            s.event(7, &[address as u32, value]);
            value
        })
    }
    unsafe fn write_register(address: usize, value: u32) {
        STATE.with(|state| {
            let mut s = state.borrow_mut();
            match address {
                0x6000e000 | 0x6000e004 => {
                    let i = (address - 0x6000e000) / 4;
                    assert_eq!(value, 1 << 26);
                    assert!(!s.reset[i]);
                    s.reset[i] = true;
                }
                0x6001c400 => s.mmio = value,
                _ => panic!("Unknown register"),
            }
            s.event(8, &[address as u32, value]);
        });
    }
    unsafe fn parameter(offset: usize) -> u8 {
        STATE.with(|state| {
            let mut s = state.borrow_mut();
            let value = match offset {
                0xe4 => s.case[9],
                0x98 => s.case[10],
                _ => panic!("Unknown parameter"),
            } as u8;
            s.event(1, &[1, offset as u32, value as u32]);
            value
        })
    }
    unsafe fn power(value: i32) {
        STATE.with(|s| s.borrow_mut().event(9, &[1, value as u32]));
    }
}
#[cfg(esp32s3)]
impl phy_basic::Calibration for Boundary {
    unsafe fn read(&self, index: usize) -> u8 {
        assert!(index < 3);
        STATE.with(|state| {
            let mut s = state.borrow_mut();
            let value = s.case[12 + index] as u8;
            s.event(3, &[1, index as u32, value as u32]);
            value
        })
    }
}
fn execute(case: [u32; 16]) -> u32 {
    STATE.with(|state| {
        *state.borrow_mut() = State {
            case,
            hosts: [case[2], case[3]],
            remaining: [case[4], case[5]],
            mmio: case[8],
            ..State::default()
        };
    });
    unsafe {
        match case[0] {
            0 => phy_basic::reset::<Boundary>(),
            1 => phy_basic::channel14::<Boundary>(case[1]),
            #[cfg(esp32s3)]
            2 => return phy_basic::interpolate(&Boundary, case[1]),
            _ => panic!("Unsupported operation"),
        }
    }
    0
}
#[test]
fn source_matches_original_instructions_and_ordered_effects() {
    let bytes =
        std::fs::read(std::env::var("PHY_BASIC_CASES").expect("Oracle cases required")).unwrap();
    assert_eq!(bytes.len() % 4, 0);
    let words: Vec<u32> = bytes
        .chunks_exact(4)
        .map(|b| u32::from_le_bytes(b.try_into().unwrap()))
        .collect();
    let (mut position, mut count) = (0, 0);
    let mut coverage = [0; 3];
    while position < words.len() {
        assert!(position + 18 <= words.len());
        let case: [u32; 16] = words[position..position + 16].try_into().unwrap();
        let expected = words[position + 16];
        let events = words[position + 17] as usize;
        position += 18;
        assert!(events <= 32 && position + 5 * events <= words.len());
        assert_eq!(execute(case), expected, "Return differs for {case:?}");
        STATE.with(|s| {
            assert_eq!(
                s.borrow().trace,
                &words[position..position + 5 * events],
                "Effects differ for {case:?}"
            )
        });
        coverage[case[0] as usize] += 1;
        count += 1;
        position += 5 * events;
    }
    assert_eq!(
        count,
        std::env::var("PHY_BASIC_CASE_COUNT")
            .unwrap()
            .parse::<usize>()
            .unwrap()
    );
    assert!(coverage[..2].iter().all(|n| *n > 0));
    #[cfg(esp32s3)]
    assert!(coverage[2] > 0);
    assert_eq!(position, words.len());
}
