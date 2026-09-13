//! Exercise production IRAM algorithms against original instruction traces.
#[path = "../../../esp-wifi-hal/src/phy_i2c_iram.rs"]
mod phy_i2c_iram;
use std::cell::RefCell;

#[cfg(esp32c3)]
const PARAM_SIZE: usize = 848;
#[cfg(esp32s3)]
const PARAM_SIZE: usize = 740;
struct State {
    case: [u32; 32],
    memory: [u8; PARAM_SIZE],
    input: [u8; 9],
    table: u32,
    callbacks: u32,
    reads: u32,
    command: u32,
    control: u32,
    trace: Vec<u32>,
}
impl State {
    fn new(case: [u32; 32]) -> Self {
        let mut memory = [0; PARAM_SIZE];
        for (offset, byte) in memory.iter_mut().enumerate() {
            *byte = ((offset as u32 * 37) ^ case[5]) as u8;
        }
        memory[0x2cd] = case[24] as u8;
        let mut fallback = Vec::new();
        let mut input = Vec::new();
        for word in &case[25..28] {
            fallback.extend(word.to_le_bytes());
        }
        for word in &case[28..31] {
            input.extend(word.to_le_bytes());
        }
        memory[0x2ce..0x2d7].copy_from_slice(&fallback[..9]);
        Self {
            case,
            memory,
            input: input[..9].try_into().unwrap(),
            table: 0,
            callbacks: 0,
            reads: 0,
            command: 0,
            control: case[18],
            trace: vec![],
        }
    }
    fn event(&mut self, kind: u32, args: &[u32]) {
        assert!(args.len() <= 8);
        let mut event = [0; 9];
        event[0] = kind;
        event[1..1 + args.len()].copy_from_slice(args);
        self.trace.extend(event);
    }
    fn mutate(&mut self) {
        assert!(self.callbacks < 64);
        let bit = 1u64 << self.callbacks;
        if (self.case[13] as u64 | ((self.case[14] as u64) << 32)) & bit != 0 {
            self.table += 1;
        }
        if (self.case[15] as u64 | ((self.case[16] as u64) << 32)) & bit != 0 {
            for byte in &mut self.memory {
                *byte ^= self.case[17] as u8;
            }
        }
        if (self.case[21] as u64 | ((self.case[22] as u64) << 32)) & bit != 0 {
            self.control ^= self.case[20];
        }
        self.callbacks += 1;
    }
    fn callback(&mut self, (slot, generation): (usize, u32), args: &[u32]) {
        let mut fields = vec![slot as u32, generation];
        fields.extend(args);
        self.event(6, &fields);
        self.mutate();
    }
}
thread_local! { static STATE: RefCell<State> = RefCell::new(State::new([0;32])); }
struct Boundary;
impl phy_i2c_iram::Access for Boundary {
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
    #[cfg(esp32s3)]
    unsafe fn write8(offset: usize, value: u8) {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.memory[offset] = value;
            s.event(2, &[1, offset as u32, value as u32]);
        });
    }
    #[cfg(esp32s3)]
    unsafe fn input8(_input: *const u8, index: usize) -> u8 {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            let v = s.input[index];
            s.event(3, &[1, index as u32, v as u32]);
            v
        })
    }
    unsafe fn read_register(address: u32) -> u32 {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            let target = s.case[8].wrapping_add(0x18003800).wrapping_shl(2);
            assert!(address == 0x6000e048 || (s.case[0] == 2 && address == target));
            let mut v = if address == 0x6000e048 {
                s.control
            } else {
                s.command
            };
            v ^= s.case[19].rotate_left(s.reads % 32);
            if s.case[0] == 2 {
                if s.reads < s.case[23] {
                    v |= 1 << 25;
                } else {
                    v &= !(1 << 25);
                }
            }
            s.reads += 1;
            s.event(7, &[address, v]);
            v
        })
    }
    unsafe fn write_register(address: u32, value: u32) {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            let target = s.case[8].wrapping_add(0x18003800).wrapping_shl(2);
            assert!(address == 0x6000e048 || (s.case[0] == 2 && address == target));
            if address == 0x6000e048 {
                s.control = value;
            } else {
                s.command = value;
            }
            s.event(8, &[address, value]);
        });
    }
    unsafe fn table() -> Self::Table {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            let generation = s.table;
            s.event(4, &[generation]);
            generation
        })
    }
    unsafe fn slot(table: u32, offset: usize) -> Self::Function {
        STATE.with(|s| s.borrow_mut().event(5, &[offset as u32, table]));
        (offset, table)
    }
    unsafe fn pause(function: Self::Function) -> u32 {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.callback(function, &[]);
            s.case[6]
        })
    }
    unsafe fn resume(function: Self::Function, token: u32) {
        STATE.with(|s| s.borrow_mut().callback(function, &[token]));
    }
    unsafe fn block_value(function: Self::Function, block: u32) -> u32 {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.callback(function, &[block]);
            #[cfg(esp32c3)]
            let host = 0x180;
            #[cfg(esp32s3)]
            let host = 0x15c;
            s.case[if function.0 == host { 8 } else { 7 }]
        })
    }
    unsafe fn read_original(
        function: Self::Function,
        block: u32,
        mask: u32,
        host: u32,
        reg: u32,
    ) -> u32 {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.callback(function, &[block, mask, host, reg]);
            s.case[9]
        })
    }
    unsafe fn read_reg(function: Self::Function, block: u32, host: u32, reg: u32) -> u32 {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.callback(function, &[block, host, reg]);
            s.case[if reg == 4 { 11 } else { 12 }]
        })
    }
    unsafe fn write_reg(function: Self::Function, block: u32, host: u32, reg: u32, data: u32) {
        STATE.with(|s| s.borrow_mut().callback(function, &[block, host, reg, data]));
    }
    #[cfg(esp32s3)]
    unsafe fn write_mask(function: Self::Function, args: [u32; 6]) {
        STATE.with(|s| s.borrow_mut().callback(function, &args));
    }
    unsafe fn read_mask(function: Self::Function, args: [u32; 5]) -> u32 {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.callback(function, &args);
            s.case[10]
        })
    }
    unsafe fn batch(function: Self::Function, data_a: [u8; 10], data_b: [u8; 10]) {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.event(11, &[function.0 as u32, function.1, 10, 0]);
            let arrays = [
                [107; 10],
                [1, 2, 3, 4, 5, 6, 7, 8, 10, 11],
                data_a,
                [98, 98, 98, 98, 98, 98, 99, 100, 100, 103],
                [3, 8, 10, 9, 4, 0, 1, 8, 4, 2],
                data_b,
            ];
            for (index, array) in arrays.iter().enumerate() {
                let mut bytes = [0; 12];
                bytes[..10].copy_from_slice(array);
                s.event(
                    12,
                    &[
                        index as u32,
                        u32::from_le_bytes(bytes[..4].try_into().unwrap()),
                        u32::from_le_bytes(bytes[4..8].try_into().unwrap()),
                        u32::from_le_bytes(bytes[8..].try_into().unwrap()),
                    ],
                );
            }
            s.mutate();
        });
    }
    unsafe fn enter() {
        STATE.with(|s| s.borrow_mut().event(9, &[]));
    }
    unsafe fn exit() {
        STATE.with(|s| s.borrow_mut().event(10, &[]));
    }
    unsafe fn init2() {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.event(14, &[]);
            s.mutate();
        });
    }
    #[cfg(esp32c3)]
    unsafe fn sar2(arg: u32) {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.event(13, &[arg]);
            s.mutate();
        });
    }
    #[cfg(esp32s3)]
    unsafe fn sar2(function: Self::Function, arg: u32) {
        STATE.with(|s| s.borrow_mut().callback(function, &[arg]));
    }
}
#[test]
fn matches_original_iram_instructions() {
    let bytes = std::fs::read(std::env::var("I2C_IRAM_CASES").unwrap()).unwrap();
    assert_eq!(bytes.len() % 4, 0);
    let words: Vec<u32> = bytes
        .chunks_exact(4)
        .map(|b| u32::from_le_bytes(b.try_into().unwrap()))
        .collect();
    let mut cursor = 0;
    let mut cases = 0;
    let mut ops = [0; 10];
    while cursor < words.len() {
        let case: [u32; 32] = words[cursor..cursor + 32].try_into().unwrap();
        cursor += 32;
        let expected = words[cursor];
        let events = words[cursor + 1] as usize;
        cursor += 2;
        STATE.with(|s| *s.borrow_mut() = State::new(case));
        let actual = unsafe {
            match case[0] {
                0 => phy_i2c_iram::hostid::<Boundary>(case[1]),
                1 => phy_i2c_iram::read::<Boundary>(case[1], case[2], case[3]),
                2 => {
                    phy_i2c_iram::write::<Boundary>(case[1], case[2], case[3], case[4]);
                    0
                }
                3 => {
                    phy_i2c_iram::init1::<Boundary>();
                    0
                }
                4 => {
                    phy_i2c_iram::wakeup::<Boundary>();
                    0
                }
                #[cfg(esp32c3)]
                5 => {
                    phy_i2c_iram::bias_dreg::<Boundary>(case[1]);
                    0
                }
                #[cfg(esp32c3)]
                6 => {
                    phy_i2c_iram::bias_part0::<Boundary>();
                    0
                }
                #[cfg(esp32s3)]
                7 => {
                    phy_i2c_iram::txcap::<Boundary>(std::ptr::null(), case[2]);
                    0
                }
                8 => {
                    <Boundary as phy_i2c_iram::Access>::enter();
                    0
                }
                9 => {
                    <Boundary as phy_i2c_iram::Access>::exit();
                    0
                }
                _ => panic!("unknown operation"),
            }
        };
        assert_eq!(actual, expected, "return case{cases} {case:?}");
        STATE.with(|s| {
            let trace = &s.borrow().trace;
            let expected = &words[cursor..cursor + events * 9];
            if trace != expected {
                let first = trace
                    .chunks(9)
                    .zip(expected.chunks(9))
                    .position(|(a, b)| a != b)
                    .unwrap_or(trace.len().min(expected.len()) / 9);
                panic!(
                    "case{cases} {case:?}: event{first}; actual {:?}, expected {:?}; counts {}/{}",
                    trace.chunks(9).nth(first),
                    expected.chunks(9).nth(first),
                    trace.len() / 9,
                    events
                );
            }
        });
        cursor += events * 9;
        ops[case[0] as usize] += 1;
        cases += 1;
    }
    assert!(ops[..5].iter().all(|n| *n > 0));
    assert!(ops[8..].iter().all(|n| *n > 0));
    assert_eq!(
        cases,
        std::env::var("I2C_IRAM_CASE_COUNT")
            .unwrap()
            .parse::<usize>()
            .unwrap()
    );
    println!("{cases} original IRAM instruction cases; operations{ops:?}");
}
