//! Run the actual source dispatcher against original-instruction oracle traces.
#[path = "../../../esp-wifi-hal/src/phy_dispatcher.rs"]
mod phy_dispatcher;
use std::cell::RefCell;

struct State {
    memory: [u8; 848],
    generation: u32,
    token: u32,
    hooks: u32,
    trace: Vec<u32>,
}
impl Default for State {
    fn default() -> Self {
        Self {
            memory: [0; 848],
            generation: 0,
            token: 0,
            hooks: 0,
            trace: vec![],
        }
    }
}
thread_local! { static STATE: RefCell<State> = RefCell::new(State::default()); }
impl State {
    fn event(&mut self, kind: u32, a: u32, b: u32) {
        self.trace.extend([kind, a, b, 0]);
    }
    fn table(&mut self, slot: usize) {
        self.event(3, self.generation, 0);
        self.event(4, slot as u32, self.generation);
    }
    // Test-only opaque helper effects. The instruction interpreter uses its own
    // memory model with these same specified helper-side mutations.
    fn helper(&mut self, kind: u32, a: u32, b: u32) {
        self.event(kind, a, b);
        match kind {
            5 => {
                if self.hooks & 1 != 0 {
                    self.generation += 1;
                }
                if self.hooks & 64 != 0 {
                    #[cfg(esp32s3)]
                    self.memory[0x2a0..0x2a4].fill(0);
                    #[cfg(esp32c3)]
                    {
                        self.memory[0x320] = 0;
                        self.memory[0x31f] = 0;
                    }
                }
            }
            7 => {
                if self.hooks & 2 != 0 {
                    self.generation += 1;
                }
                if self.hooks & 4 != 0 {
                    self.memory[0x9c] = 255;
                    self.memory[0x9b] = 91;
                    self.memory[0x216] = 1;
                }
            }
            8 => {
                if self.hooks & 8 != 0 {
                    self.memory[0x9c] = 128;
                    self.memory[0x9b] = 127;
                }
            }
            9 => {
                if self.hooks & 16 != 0 {
                    self.memory[0x216] = 255;
                    self.memory[0x9b] = 201;
                }
                if self.hooks & 32 != 0 {
                    self.generation += 1;
                }
            }
            10 => {
                if self.hooks & 128 != 0 {
                    self.generation += 1;
                }
            }
            _ => {}
        }
    }
}
struct Boundary;
impl phy_dispatcher::Access for Boundary {
    unsafe fn read8(offset: usize) -> u8 {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            let v = s.memory[offset];
            s.event(1, offset as u32, v as u32);
            v
        })
    }
    #[cfg(esp32s3)]
    unsafe fn read32(offset: usize) -> u32 {
        assert_eq!(offset % 4, 0);
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            let v = u32::from_le_bytes(s.memory[offset..offset + 4].try_into().unwrap());
            s.event(2, offset as u32, v);
            v
        })
    }
    unsafe fn enter(slot: usize) -> u32 {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.table(slot);
            let token = s.token;
            s.helper(5, slot as u32, token);
            token
        })
    }
    unsafe fn exit(slot: usize, token: u32) {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.table(slot);
            s.helper(6, slot as u32, token);
        })
    }
    #[cfg(esp32s3)]
    unsafe fn table_temperature(slot: usize) {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.table(slot);
            s.helper(7, slot as u32, 0);
        })
    }
    #[cfg(esp32s3)]
    unsafe fn table_power(slot: usize, enabled: u8, mode: u8) {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.table(slot);
            s.helper(8, enabled as u32, mode as u32);
        })
    }
    #[cfg(esp32c3)]
    unsafe fn temperature() {
        STATE.with(|s| s.borrow_mut().helper(7, 0, 0));
    }
    #[cfg(esp32c3)]
    unsafe fn power(enabled: u8, mode: u8) {
        STATE.with(|s| s.borrow_mut().helper(8, enabled as u32, mode as u32));
    }
    unsafe fn pll(value: u8) {
        STATE.with(|s| s.borrow_mut().helper(9, value as u32, 0));
    }
    #[cfg(esp32c3)]
    unsafe fn rfcal(value: u8, threshold: u8) {
        STATE.with(|s| s.borrow_mut().helper(10, value as u32, threshold as u32));
    }
}

#[test]
fn source_matches_every_original_instruction_case_and_adversarial_helper_trace() {
    let bytes =
        std::fs::read(std::env::var("PHY_ORACLE_CASES").expect("oracle case file required"))
            .unwrap();
    assert_eq!(bytes.len() % 4, 0);
    let words: Vec<u32> = bytes
        .chunks_exact(4)
        .map(|w| u32::from_le_bytes(w.try_into().unwrap()))
        .collect();
    let mut position = 0;
    let mut count = 0;
    while position < words.len() {
        let case = &words[position..position + 9];
        let events = words[position + 9] as usize;
        position += 10;
        let expected = &words[position..position + events * 4];
        position += events * 4;
        STATE.with(|state| {
            let mut s = state.borrow_mut();
            *s = State::default();
            #[cfg(esp32c3)]
            {
                s.memory[0x320] = case[2] as u8;
                s.memory[0x31f] = (case[2] >> 8) as u8;
            }
            #[cfg(esp32s3)]
            s.memory[0x2a0..0x2a4].copy_from_slice(&((case[2] << 16) | case[3]).to_le_bytes());
            s.memory[0x9c] = case[4] as u8;
            s.memory[0x9b] = case[5] as u8;
            s.memory[0x216] = case[6] as u8;
            s.token = case[7];
            s.hooks = case[8];
        });
        unsafe {
            phy_dispatcher::dispatch::<Boundary>(case[0] as u8, case[1] as u8);
        }
        STATE.with(|s| assert_eq!(s.borrow().trace, expected, "case {count}: {case:?}"));
        count += 1;
    }
    #[cfg(esp32c3)]
    assert_eq!(count, 137216);
    #[cfg(esp32s3)]
    assert_eq!(count, 268288);
}
