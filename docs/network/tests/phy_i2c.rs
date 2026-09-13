//! Compare the production I2C source with the original-instruction corpus.
#[path = "../../../esp-wifi-hal/src/phy_i2c.rs"]
mod phy_i2c;
use std::cell::RefCell;

#[cfg(esp32c3)]
const PARAM_SIZE: usize = 848;
#[cfg(esp32s3)]
const PARAM_SIZE: usize = 740;
struct State {
    case: [u32; 24],
    memory: [u8; PARAM_SIZE],
    reads: u32,
    generation: u32,
    callbacks: u32,
    trace: Vec<u32>,
}
impl State {
    fn new(case: [u32; 24]) -> Self {
        let mut memory = [0; PARAM_SIZE];
        for (offset, byte) in memory.iter_mut().enumerate() {
            *byte = ((offset as u32 * 37) ^ case[2]) as u8;
        }
        memory[0x9f] = case[3] as u8;
        memory[0x20d] = case[4] as u8;
        #[cfg(esp32c3)]
        let gate = 0x323;
        #[cfg(esp32s3)]
        let gate = 0x2a6;
        memory[gate] = case[5] as u8;
        for (offset, value) in (0x167..0x16f).zip(&case[6..14]) {
            memory[offset] = *value as u8;
        }
        Self {
            case,
            memory,
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
        assert!(self.callbacks < 64);
        let mask = 1u64 << self.callbacks;
        if (self.case[18] as u64 | ((self.case[19] as u64) << 32)) & mask != 0 {
            self.generation += 1;
        }
        if (self.case[20] as u64 | ((self.case[21] as u64) << 32)) & mask != 0 {
            for byte in &mut self.memory {
                *byte ^= self.case[22] as u8;
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
impl phy_i2c::Access for Boundary {
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
    unsafe fn write8(offset: usize, value: u8) {
        write(offset, &[value]);
    }
    #[cfg(esp32c3)]
    unsafe fn write16(offset: usize, value: u16) {
        write(offset, &value.to_le_bytes());
    }
    #[cfg(esp32c3)]
    unsafe fn write32(offset: usize, value: u32) {
        write(offset, &value.to_le_bytes());
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
    unsafe fn read_reg(function: Self::Function, block: u32, host: u32, reg: u32) -> u32 {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.callback(function, &[block, host, reg]);
            let v = s.case[14 + s.reads as usize];
            s.reads += 1;
            v
        })
    }
    unsafe fn write_reg(function: Self::Function, block: u32, host: u32, reg: u32, data: u32) {
        STATE.with(|s| s.borrow_mut().callback(function, &[block, host, reg, data]));
    }
    unsafe fn write_mask(function: Self::Function, args: [u32; 6]) {
        STATE.with(|s| s.borrow_mut().callback(function, &args));
    }
    #[cfg(esp32c3)]
    unsafe fn direct_bias(arg: u32) {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.event(9, &[arg]);
            s.after_callback();
        });
    }
    #[cfg(esp32c3)]
    unsafe fn direct_bias_part0() {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.event(10, &[]);
            s.after_callback();
        });
    }
}
fn write(offset: usize, bytes: &[u8]) {
    assert_eq!(offset % bytes.len(), 0);
    STATE.with(|s| {
        let mut s = s.borrow_mut();
        s.memory[offset..offset + bytes.len()].copy_from_slice(bytes);
        let mut v = [0; 4];
        v[..bytes.len()].copy_from_slice(bytes);
        s.event(
            2,
            &[bytes.len() as u32, offset as u32, u32::from_le_bytes(v)],
        );
    });
}

#[test]
fn matches_original_instructions() {
    let path = std::env::var("I2C_CASES").expect("I2C_CASES must name the oracle corpus");
    let bytes = std::fs::read(path).unwrap();
    assert_eq!(bytes.len() % 4, 0);
    let words: Vec<u32> = bytes
        .chunks_exact(4)
        .map(|b| u32::from_le_bytes(b.try_into().unwrap()))
        .collect();
    let mut cursor = 0;
    let mut cases = 0;
    let mut ops = [0; 4];
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
                0 => phy_i2c::get_data::<Boundary>(),
                1 => phy_i2c::bias::<Boundary>(case[1]),
                2 => phy_i2c::bbpll::<Boundary>(),
                3 => phy_i2c::init2::<Boundary>(),
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
        std::env::var("I2C_CASE_COUNT")
            .unwrap()
            .parse::<usize>()
            .unwrap()
    );
    println!("{cases} original-instruction cases; operations {ops:?}");
}
