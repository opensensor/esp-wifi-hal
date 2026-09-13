//! Exercise the production source against the pinned original-instruction oracle.
#[path = "../../../esp-wifi-hal/src/phy_lifecycle.rs"]
mod phy_lifecycle;
use std::cell::RefCell;

#[cfg(esp32c3)]
const REGISTERS: [usize; 4] = [0x60040058, 0x600c0014, 0x600c001c, 0x6004005c];
#[cfg(esp32s3)]
const REGISTERS: [usize; 4] = [0x60008850, 0x60008034, 0x60008904, 0];
#[cfg(esp32c3)]
const OFFSETS: [usize; 4] = [0x20c, 0x210, 0x212, 0x31f];
#[cfg(esp32s3)]
const OFFSETS: [usize; 4] = [0x206, 0x20a, 0, 0x2a2];
struct State {
    case: [u32; 22],
    memory: [u8; 848],
    registers: [u32; 4],
    reads: u32,
    generation: u32,
    trace: Vec<u32>,
}
impl Default for State {
    fn default() -> Self {
        Self {
            case: [0; 22],
            memory: [0; 848],
            registers: [0; 4],
            reads: 0,
            generation: 0,
            trace: vec![],
        }
    }
}
impl State {
    fn event(&mut self, kind: u32, fields: &[u32]) {
        assert!(fields.len() <= 8);
        let mut event = [0; 9];
        event[0] = kind;
        event[1..1 + fields.len()].copy_from_slice(fields);
        self.trace.extend(event);
    }
    fn store16(&mut self, offset: usize, value: u32) {
        assert_eq!(offset % 2, 0);
        self.memory[offset..offset + 2].copy_from_slice(&(value as u16).to_le_bytes());
    }
    fn measure(&mut self) {
        self.store16(0x92, self.case[15]);
        let hooks = self.case[16];
        if hooks & 1 != 0 {
            self.memory[0x204] = self.case[17] as u8;
        }
        for (bit, offset, value) in [
            (2, OFFSETS[0], self.case[18]),
            (4, OFFSETS[1], self.case[19]),
            (8, OFFSETS[2], self.case[20]),
        ] {
            if hooks & bit != 0 && offset != 0 {
                self.store16(offset, value);
            }
        }
        if hooks & 16 != 0 {
            self.generation += 1;
        }
    }
}
thread_local! { static STATE: RefCell<State> = RefCell::new(State::default()); }
struct Boundary;
impl phy_lifecycle::Access for Boundary {
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
    unsafe fn write8(offset: usize, value: u8) {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.memory[offset] = value;
            s.event(2, &[1, offset as u32, value as u32]);
        });
    }
    unsafe fn write16(offset: usize, value: u16) {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.store16(offset, value as u32);
            s.event(2, &[2, offset as u32, value as u32]);
        });
    }
    unsafe fn read_register(address: usize) -> u32 {
        let index = REGISTERS
            .iter()
            .position(|a| *a == address && address != 0)
            .expect("unexpected MMIO read");
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            let v = s.registers[index] ^ s.case[14].rotate_left(s.reads % 32);
            s.reads += 1;
            s.event(7, &[address as u32, v]);
            v
        })
    }
    unsafe fn write_register(address: usize, value: u32) {
        let index = REGISTERS
            .iter()
            .position(|a| *a == address && address != 0)
            .expect("unexpected MMIO write");
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.registers[index] = value;
            s.event(8, &[address as u32, value]);
        });
    }
    #[cfg(esp32c3)]
    unsafe fn attribute8(offset: usize) -> u8 {
        let v = phy_lifecycle::ATTRIBUTE_BYTES[offset];
        STATE.with(|s| s.borrow_mut().event(3, &[1, offset as u32, v as u32]));
        v
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
        #[cfg(esp32c3)]
        assert_eq!(offset, 0x1bc);
        #[cfg(esp32s3)]
        assert_eq!(offset, 0x258);
        STATE.with(|s| s.borrow_mut().event(5, &[offset as u32, table]));
        (offset, table)
    }
    #[cfg(esp32c3)]
    unsafe fn write_dac((slot, generation): Self::Function, dac: u8) {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.event(6, &[slot as u32, generation, 105, 0, 6, 3, 0, dac as u32]);
            if s.case[16] & 32 != 0 {
                s.generation += 1;
            }
            if s.case[16] & 64 != 0 {
                s.registers[0] ^= s.case[21];
            }
        });
    }
    #[cfg(esp32s3)]
    unsafe fn table_measure((slot, generation): Self::Function) {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.event(6, &[slot as u32, generation, 0, 0, 0, 0, 0, 0]);
            s.measure();
        });
    }
    #[cfg(esp32c3)]
    unsafe fn direct_measure() {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.event(9, &[]);
            s.measure();
        });
    }
}
fn execute(case: [u32; 22]) -> u32 {
    STATE.with(|s| {
        let mut s = s.borrow_mut();
        *s = State::default();
        s.case = case;
        s.memory[0x204] = case[4] as u8;
        s.store16(0x92, case[5]);
        s.store16(OFFSETS[0], case[6]);
        s.store16(OFFSETS[1], case[7]);
        if OFFSETS[2] != 0 {
            s.store16(OFFSETS[2], case[8]);
        }
        s.memory[OFFSETS[3]] = case[9] as u8;
        s.registers.copy_from_slice(&case[10..14]);
    });
    unsafe {
        match case[0] {
            0 => phy_lifecycle::power::<Boundary>(case[1]),
            1 => phy_lifecycle::read_init::<Boundary>(case[1], case[2]),
            2 => phy_lifecycle::xpd::<Boundary>(),
            #[cfg(esp32s3)]
            3 => return phy_lifecycle::code::<Boundary>(),
            4 => return phy_lifecycle::temp_to_power(case[1], case[2], case[3]),
            5 => phy_lifecycle::get_temp_init::<Boundary>(case[1], case[2]),
            _ => panic!("unsupported lifecycle operation"),
        }
    }
    0
}
#[test]
fn source_matches_original_instructions_and_ordered_effects() {
    let bytes = std::fs::read(std::env::var("PHY_LIFECYCLE_CASES").expect("oracle cases required"))
        .unwrap();
    assert_eq!(bytes.len() % 4, 0);
    let words: Vec<u32> = bytes
        .chunks_exact(4)
        .map(|b| u32::from_le_bytes(b.try_into().unwrap()))
        .collect();
    let mut pos = 0;
    let mut count = 0;
    let mut coverage = [0usize; 6];
    while pos < words.len() {
        assert!(pos + 24 <= words.len());
        let case = words[pos..pos + 22].try_into().unwrap();
        let returned = words[pos + 22];
        let events = words[pos + 23] as usize;
        pos += 24;
        assert!(pos + 9 * events <= words.len());
        assert_eq!(execute(case), returned, "return case {case:?}");
        STATE.with(|s| {
            assert_eq!(
                s.borrow().trace,
                &words[pos..pos + 9 * events],
                "trace case {case:?}"
            )
        });
        pos += 9 * events;
        count += 1;
        coverage[case[0] as usize] += 1;
    }
    assert_eq!(
        count,
        std::env::var("PHY_LIFECYCLE_CASE_COUNT")
            .expect("pinned count required")
            .parse::<usize>()
            .unwrap()
    );
    for (op, n) in coverage.iter().enumerate() {
        if cfg!(esp32c3) && op == 3 {
            assert_eq!(*n, 0);
        } else {
            assert!(*n > 0, "missing operation {op}");
        }
    }
}
#[test]
fn source_table_preserves_all_rows_and_alignment() {
    assert_eq!(
        phy_lifecycle::ATTRIBUTE_BYTES,
        [
            254, 5, 50, 0, 125, 0, 255, 7, 20, 0, 100, 0, 0, 15, 246, 255, 80, 0, 1, 11, 226, 255,
            50, 0, 2, 10, 216, 255, 20, 0
        ]
    );
    assert_eq!(std::mem::align_of::<phy_lifecycle::Attributes>(), 2);
    assert_eq!(std::mem::size_of::<phy_lifecycle::Attributes>(), 30);
}
#[cfg(esp32c3)]
#[test]
fn invalid_init_index_is_guarded_only_if_row_is_used() {
    for index in [5, 6, 255, 256, 0x80000000, u32::MAX] {
        let mut case = [0; 22];
        case[0] = 1;
        case[2] = index;
        assert_eq!(execute(case), 0);
        case[1] = 1;
        assert!(std::panic::catch_unwind(|| execute(case)).is_err());
        STATE.with(|s| assert!(s.borrow().trace.is_empty()));
    }
}
