//! Compare production temperature logic with independently interpreted instructions.
#[path = "../../../esp-wifi-hal/src/phy_temperature.rs"]
mod phy_temperature;
use std::cell::RefCell;

const ATTRIBUTES: [u8; 30] = [
    254, 5, 50, 0, 125, 0, 255, 7, 20, 0, 100, 0, 0, 15, 246, 255, 80, 0, 1, 11, 226, 255, 50, 0,
    2, 10, 216, 255, 20, 0,
];
#[cfg(esp32c3)]
const SLOTS: [usize; 4] = [0x1ac, 0x208, 0x218, 0x1bc];
#[cfg(esp32s3)]
const SLOTS: [usize; 4] = [0x188, 0x1e4, 0x1f4, 0x198];
struct State {
    memory: [u8; 848],
    case: [u32; 10],
    generation: u32,
    trace: Vec<u32>,
}
impl Default for State {
    fn default() -> Self {
        Self {
            memory: [0xa5; 848],
            case: [0; 10],
            generation: 0,
            trace: vec![],
        }
    }
}
impl State {
    fn event(&mut self, kind: u32, values: &[u32]) {
        assert!(values.len() <= 8);
        let mut event = [0; 9];
        event[0] = kind;
        event[1..1 + values.len()].copy_from_slice(values);
        self.trace.extend(event);
    }
}
thread_local! { static STATE: RefCell<State> = RefCell::new(State::default()); }
struct Boundary;
impl phy_temperature::Access for Boundary {
    type Table = u32;
    type Function = (usize, u32);
    unsafe fn read8(offset: usize) -> u8 {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            let value = s.memory[offset];
            s.event(1, &[1, offset as u32, value as u32]);
            value
        })
    }
    unsafe fn write8(offset: usize, value: u8) {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.memory[offset] = value;
            s.event(2, &[1, offset as u32, value as u32]);
        });
    }
    unsafe fn write16(offset: usize, value: u16) {
        assert_eq!(offset % 2, 0);
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.memory[offset..offset + 2].copy_from_slice(&value.to_le_bytes());
            s.event(2, &[2, offset as u32, value as u32]);
        });
    }
    unsafe fn attribute8(offset: usize) -> u8 {
        let value = ATTRIBUTES[offset];
        STATE.with(|s| s.borrow_mut().event(3, &[1, offset as u32, value as u32]));
        value
    }
    unsafe fn attribute16(offset: usize) -> u16 {
        assert_eq!(offset % 2, 0);
        let value = u16::from_le_bytes(ATTRIBUTES[offset..offset + 2].try_into().unwrap());
        STATE.with(|s| s.borrow_mut().event(3, &[2, offset as u32, value as u32]));
        value
    }
    unsafe fn table() -> Self::Table {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            let generation = s.generation;
            s.event(4, &[generation]);
            generation
        })
    }
    unsafe fn slot(table: Self::Table, offset: usize) -> Self::Function {
        assert!(SLOTS.contains(&offset));
        STATE.with(|s| s.borrow_mut().event(5, &[offset as u32, table]));
        (offset, table)
    }
    unsafe fn call((slot, generation): Self::Function, args: [u32; 6]) -> u32 {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.event(
                6,
                &[
                    slot as u32,
                    generation,
                    args[0],
                    args[1],
                    args[2],
                    args[3],
                    args[4],
                    args[5],
                ],
            );
            let index = SLOTS.iter().position(|v| *v == slot).unwrap();
            let hooks = s.case[7];
            if hooks & (1 << index) != 0 {
                s.generation += 1;
            }
            if index == 1 && hooks & 16 != 0 {
                s.memory[0xaa] = s.case[8] as u8;
            }
            if index == 2 && hooks & 32 != 0 {
                s.memory[0xaa] = s.case[9] as u8;
            }
            match index {
                0 => s.case[3],
                1 => s.case[4],
                2 => s.case[5],
                3 => 0xdeadbeef,
                _ => unreachable!(),
            }
        })
    }
}
fn execute(case: [u32; 10]) -> u32 {
    STATE.with(|s| {
        let mut s = s.borrow_mut();
        *s = State::default();
        s.case = case;
        s.memory[0xaa] = case[6] as u8;
    });
    unsafe {
        match case[0] {
            0 => phy_temperature::decode(case[1]),
            1 => phy_temperature::range::<Boundary>(case[1] as i32, case[2]),
            2 => phy_temperature::inner::<Boundary>(),
            3 => phy_temperature::forward::<Boundary>(),
            4 => phy_temperature::outer::<Boundary>(),
            _ => panic!("unknown operation"),
        }
    }
}
#[test]
fn source_matches_original_instructions_and_helper_side_effects() {
    let bytes =
        std::fs::read(std::env::var("PHY_TEMPERATURE_CASES").expect("oracle cases required"))
            .unwrap();
    assert_eq!(bytes.len() % 4, 0);
    let words: Vec<u32> = bytes
        .chunks_exact(4)
        .map(|w| u32::from_le_bytes(w.try_into().unwrap()))
        .collect();
    let mut position = 0;
    let mut count = 0;
    while position < words.len() {
        let case: [u32; 10] = words[position..position + 10].try_into().unwrap();
        let returned = words[position + 10];
        let events = words[position + 11] as usize;
        position += 12;
        let expected = &words[position..position + events * 9];
        position += events * 9;
        assert_eq!(execute(case), returned, "return: case {count}: {case:?}");
        STATE.with(|s| {
            let s = s.borrow();
            assert_eq!(s.trace, expected, "trace: case {count}: {case:?}");
            for (offset, value) in s.memory.iter().enumerate() {
                if ![0x92, 0x93, 0xaa].contains(&offset) {
                    assert_eq!(*value, 0xa5);
                }
            }
        });
        count += 1;
    }
    #[cfg(esp32c3)]
    assert_eq!(count, 366074);
    #[cfg(esp32s3)]
    assert_eq!(count, 366099);
    println!("Matched {count} temperature instruction cases");
}
#[test]
fn unsupported_row_is_rejected_before_any_attribute_read() {
    for index in [5, 6, 255, u32::MAX] {
        let result = std::panic::catch_unwind(|| execute([1, 20, index, 0, 0, 0, 0, 0, 0, 0]));
        assert!(result.is_err());
        STATE.with(|s| assert!(s.borrow().trace.is_empty()));
    }
}
#[test]
fn invalid_dac_and_invalid_helper_indexes_never_read_past_the_attribute_table() {
    for (dac, hooks, after_code, after_convert) in [(0, 0, 0, 0), (5, 16, 5, 0), (5, 32, 0, 255)] {
        let result = std::panic::catch_unwind(|| {
            execute([4, 0, 0, dac, 200, 20, 0, hooks, after_code, after_convert])
        });
        assert!(result.is_err());
        STATE.with(|s| {
            let s = s.borrow();
            for event in s.trace.chunks_exact(9) {
                if event[0] == 3 {
                    assert!(event[2] + event[1] <= 30);
                }
            }
            assert_eq!(&s.memory[0x92..0x94], &[0xa5, 0xa5]);
        });
    }
}
