//! Run the production PHY API source against independent original instructions.
#[path = "../../../esp-wifi-hal/src/phy_api.rs"]
mod phy_api;
use std::cell::RefCell;
struct State {
    case: [u32; 16],
    memory: [u8; 848],
    register: u32,
    generation: u32,
    trace: Vec<u32>,
}
impl Default for State {
    fn default() -> Self {
        Self {
            case: [0; 16],
            memory: [0xa5; 848],
            register: 0,
            generation: 0,
            trace: vec![],
        }
    }
}
impl State {
    fn event(&mut self, kind: u32, fields: &[u32]) {
        assert!(fields.len() <= 4);
        let mut event = [0; 5];
        event[0] = kind;
        event[1..1 + fields.len()].copy_from_slice(fields);
        self.trace.extend(event);
    }
    fn hook(&mut self, kind: usize) {
        if self.case[7] & (1 << kind) != 0 {
            if kind < 3 {
                self.memory[0x120..0x124].copy_from_slice(&self.case[9 + kind].to_le_bytes());
            }
            if kind < 2 {
                self.memory[0x1f2] = self.case[12 + kind] as u8;
            }
            #[cfg(esp32c3)]
            if kind == 3 {
                self.memory[0x31f] = self.case[14] as u8;
            }
            #[cfg(esp32c3)]
            if kind == 4 {
                self.memory[0x320] = self.case[15] as u8;
            }
        }
        if self.case[8] & (1 << kind) != 0 {
            self.generation += 1;
        }
    }
}
thread_local! { static STATE: RefCell<State> = RefCell::new(State::default()); }
struct Boundary;
fn helper(kind: usize) {
    STATE.with(|s| {
        let mut s = s.borrow_mut();
        s.event(9, &[kind as u32]);
        s.hook(kind);
    });
}
impl phy_api::Access for Boundary {
    type Table = u32;
    type Function = (usize, u32);
    unsafe fn wakeup() {
        helper(0);
    }
    unsafe fn close() {
        helper(4);
    }
    unsafe fn frequency_init() {
        helper(1);
    }
    #[cfg(esp32c3)]
    unsafe fn measure() {
        helper(3);
    }
    unsafe fn read8(offset: usize) -> u8 {
        assert!([0x1f2, 0x31f].contains(&offset));
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            let v = s.memory[offset];
            s.event(1, &[1, offset as u32, v as u32]);
            v
        })
    }
    unsafe fn read32(offset: usize) -> u32 {
        assert_eq!(offset, 0x120);
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            let v = u32::from_le_bytes(s.memory[offset..offset + 4].try_into().unwrap());
            s.event(1, &[4, offset as u32, v]);
            v
        })
    }
    unsafe fn write32(offset: usize, value: u32) {
        assert_eq!(offset, 0x120);
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.memory[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
            s.event(2, &[4, offset as u32, value]);
        });
    }
    #[cfg(esp32c3)]
    unsafe fn write8(offset: usize, value: u8) {
        assert_eq!(offset, 0x320);
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.memory[offset] = value;
            s.event(2, &[1, offset as u32, value as u32]);
        });
    }
    unsafe fn table() -> u32 {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            let v = s.generation;
            s.event(4, &[v]);
            v
        })
    }
    unsafe fn slot(table: u32, offset: usize) -> Self::Function {
        #[cfg(esp32c3)]
        assert_eq!(offset, 0xd8);
        #[cfg(esp32s3)]
        assert_eq!(offset, 0xcc);
        STATE.with(|s| s.borrow_mut().event(5, &[offset as u32, table]));
        (offset, table)
    }
    unsafe fn channel((slot, generation): Self::Function, channel: u8) {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.event(6, &[slot as u32, generation, channel as u32]);
            s.hook(2);
        });
    }
    #[cfg(esp32s3)]
    unsafe fn read_register(address: usize) -> u32 {
        assert_eq!(address, 0x6001c400);
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            let v = s.register;
            s.event(7, &[address as u32, v]);
            v
        })
    }
    #[cfg(esp32s3)]
    unsafe fn write_register(address: usize, value: u32) {
        assert_eq!(address, 0x6001c400);
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.register = value;
            s.event(8, &[address as u32, value]);
        });
    }
}
fn execute(case: [u32; 16]) -> u32 {
    STATE.with(|s| {
        let mut s = s.borrow_mut();
        *s = State::default();
        s.case = case;
        s.memory[0x120..0x124].copy_from_slice(&case[2].to_le_bytes());
        s.memory[0x1f2] = case[3] as u8;
        s.memory[0x31f] = case[4] as u8;
        s.memory[0x320] = case[5] as u8;
        s.register = case[6];
    });
    unsafe {
        match case[0] {
            0 => phy_api::wakeup::<Boundary>(),
            1 => phy_api::close::<Boundary>(),
            2 => return phy_api::calibration_version(),
            #[cfg(esp32s3)]
            3 => phy_api::set_tx_seed::<Boundary>(case[1]),
            _ => panic!("Unsupported operation"),
        }
    }
    0
}
#[test]
fn source_matches_original_instructions_and_ordered_effects() {
    let bytes =
        std::fs::read(std::env::var("PHY_API_CASES").expect("Oracle cases required")).unwrap();
    assert_eq!(bytes.len() % 4, 0);
    let words: Vec<u32> = bytes
        .chunks_exact(4)
        .map(|b| u32::from_le_bytes(b.try_into().unwrap()))
        .collect();
    let mut position = 0;
    let mut count = 0;
    let mut coverage = [0; 4];
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
        std::env::var("PHY_API_CASE_COUNT")
            .unwrap()
            .parse::<usize>()
            .unwrap()
    );
    assert!(coverage[..3].iter().all(|n| *n > 0));
    #[cfg(esp32s3)]
    assert!(coverage[3] > 0);
    assert_eq!(position, words.len());
}
