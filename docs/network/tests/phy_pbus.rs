//! Compare the production PBUS source with the original-instruction corpus.
#[path = "../../../esp-wifi-hal/src/phy_pbus.rs"]
mod phy_pbus;
use std::cell::RefCell;

const REGISTERS: [usize; 12] = [
    0x600060c8, 0x600060cc, 0x600060e0, 0x600060e4, 0x600060e8, 0x600060ec, 0x600060f0, 0x600060f4,
    0x60006104, 0x6000610c, 0x6002600c, 0x6001c02c,
];
#[cfg(esp32c3)]
const PARAM_SIZE: usize = 848;
#[cfg(esp32s3)]
const PARAM_SIZE: usize = 740;
#[cfg(esp32c3)]
const INDEX: usize = 0xa3;
#[cfg(esp32s3)]
const INDEX: usize = 0x20c;

struct State {
    case: [u32; 24],
    memory: [u8; PARAM_SIZE],
    registers: [u32; 12],
    reads: u32,
    generation: u32,
    callbacks: u32,
    trace: Vec<u32>,
}
impl State {
    fn new(case: [u32; 24]) -> Self {
        let mut memory = [0; PARAM_SIZE];
        for (offset, byte) in memory.iter_mut().enumerate() {
            *byte = ((offset as u32 * 37) ^ case[3]) as u8;
        }
        memory[INDEX] = case[2] as u8;
        Self {
            case,
            memory,
            registers: case[12..24].try_into().unwrap(),
            reads: 0,
            generation: 0,
            callbacks: 0,
            trace: vec![],
        }
    }
    fn event(&mut self, kind: u32, fields: &[u32]) {
        assert!(fields.len() <= 8);
        let mut event = [0; 9];
        event[0] = kind;
        event[1..1 + fields.len()].copy_from_slice(fields);
        self.trace.extend(event);
    }
    fn after_callback(&mut self) {
        let mask = 1 << self.callbacks;
        if self.case[5] & mask != 0 {
            self.generation += 1;
        }
        if self.case[6] & mask != 0 {
            for byte in &mut self.memory {
                *byte ^= self.case[7] as u8;
            }
        }
        self.callbacks += 1;
    }
    fn callback(&mut self, (offset, generation): (usize, u32), args: &[u32]) {
        let mut fields = vec![offset as u32, generation];
        fields.extend(args);
        self.event(6, &fields);
        self.after_callback();
    }
}
thread_local! { static STATE: RefCell<State> = RefCell::new(State::new([0;24])); }
struct Boundary;
impl phy_pbus::Access for Boundary {
    type Table = u32;
    type Function = (usize, u32);
    unsafe fn read8(offset: usize) -> u8 {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            let v = s.memory[offset];
            s.event(1, &[1, offset as u32, v as u32]);
            v
        })
    }
    unsafe fn read16(offset: usize) -> u16 {
        assert_eq!(offset % 2, 0);
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            let v = u16::from_le_bytes(s.memory[offset..offset + 2].try_into().unwrap());
            s.event(1, &[2, offset as u32, v as u32]);
            v
        })
    }
    unsafe fn write32(offset: usize, value: u32) {
        assert_eq!(offset % 4, 0);
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.memory[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
            s.event(2, &[4, offset as u32, value]);
        });
    }
    unsafe fn read_register(address: usize) -> u32 {
        let i = REGISTERS
            .iter()
            .position(|a| *a == address)
            .expect("unknown MMIO read");
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            let v = s.registers[i] ^ s.case[8].rotate_left(s.reads % 32);
            s.reads += 1;
            s.event(7, &[address as u32, v]);
            v
        })
    }
    unsafe fn write_register(address: usize, value: u32) {
        let i = REGISTERS
            .iter()
            .position(|a| *a == address)
            .expect("unknown MMIO write");
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.registers[i] = value;
            s.event(8, &[address as u32, value]);
        });
    }
    unsafe fn table() -> Self::Table {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            let v = s.generation;
            s.event(4, &[v]);
            v
        })
    }
    unsafe fn slot(table: Self::Table, offset: usize) -> Self::Function {
        STATE.with(|s| s.borrow_mut().event(5, &[offset as u32, table]));
        (offset, table)
    }
    unsafe fn call_void0(function: Self::Function) {
        STATE.with(|s| s.borrow_mut().callback(function, &[]));
    }
    unsafe fn call_clock(function: Self::Function, arg: u32) {
        STATE.with(|s| s.borrow_mut().callback(function, &[arg]));
    }
    unsafe fn call_rx(function: Self::Function, arg: u32) {
        STATE.with(|s| s.borrow_mut().callback(function, &[arg]));
    }
    unsafe fn call_void2(function: Self::Function, arg0: u32, arg1: u32) {
        STATE.with(|s| s.borrow_mut().callback(function, &[arg0, arg1]));
    }
    unsafe fn call_index(function: Self::Function, arg: u32) -> u32 {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.callback(function, &[arg]);
            s.case[4]
        })
    }
    unsafe fn call_param(function: Self::Function, offset: u32) {
        STATE.with(|s| s.borrow_mut().callback(function, &[offset]));
    }
    unsafe fn direct_stop_tone(arg: u32) {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.event(10, &[arg]);
            s.after_callback();
        });
    }
    #[cfg(esp32c3)]
    unsafe fn delay_us(micros: u32) {
        assert!((1..=2).contains(&micros));
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.event(9, &[micros]);
            s.registers[11] ^= s.case[8 + micros as usize];
        });
    }
}

#[test]
fn matches_original_instructions() {
    let path = std::env::var("PBUS_CASES").expect("PBUS_CASES must name the oracle corpus");
    let bytes = std::fs::read(path).unwrap();
    assert_eq!(bytes.len() % 4, 0);
    let words: Vec<u32> = bytes
        .chunks_exact(4)
        .map(|b| u32::from_le_bytes(b.try_into().unwrap()))
        .collect();
    let mut cursor = 0;
    let mut cases = 0;
    let mut ops = [0; 5];
    while cursor < words.len() {
        let case: [u32; 24] = words[cursor..cursor + 24].try_into().unwrap();
        cursor += 24;
        let result = words[cursor];
        let events = words[cursor + 1] as usize;
        cursor += 2;
        assert_eq!(result, 0, "void API corpus return");
        STATE.with(|s| *s.borrow_mut() = State::new(case));
        unsafe {
            match case[0] {
                #[cfg(esp32c3)]
                0 => phy_pbus::force_mode::<Boundary>(case[1]),
                1 => phy_pbus::debug_mode::<Boundary>(),
                2 => phy_pbus::work_mode::<Boundary>(),
                3 => phy_pbus::save::<Boundary>(),
                4 => phy_pbus::mem::<Boundary>(),
                _ => panic!("unknown operation"),
            }
        }
        STATE.with(|s| {
            assert_eq!(
                s.borrow().trace,
                words[cursor..cursor + events * 9],
                "case {cases}: {case:?}"
            )
        });
        cursor += events * 9;
        ops[case[0] as usize] += 1;
        cases += 1;
    }
    assert!(ops[1..].iter().all(|n| *n > 0));
    #[cfg(esp32c3)]
    assert!(ops[0] > 0);
    assert_eq!(
        cases,
        std::env::var("PBUS_CASE_COUNT")
            .unwrap()
            .parse::<usize>()
            .unwrap()
    );
    println!("{cases} original-instruction cases; operations {ops:?}");
}
