//! TX IQ calibration wrappers with ordered live callback and parameter access.

pub enum Output {
    Parameter(usize),
    Scratch,
}

pub trait Access {
    const S3: bool;
    fn read_flags(&mut self) -> u32;
    fn write_flags(&mut self, value: u32);
    fn read_attenuation(&mut self) -> u8;
    fn table(&mut self) -> u32;
    fn slot(&mut self, table: u32, offset: u32) -> u32;
    fn read_analog(&mut self, callback: u32, block: u32, host: u32, register: u32) -> u32;
    fn write_analog(&mut self, callback: u32, block: u32, host: u32, register: u32, value: u32);
    // rfcal_txiq(0, output1, phy_param+output2, tone, attenuation, mode).
    // Scratch must supply four writable, aligned halfwords for txdc_cal_v70.
    fn calibrate(
        &mut self,
        output1: Output,
        output2: usize,
        tone: u32,
        attenuation: i32,
        mode: u32,
    );
}

#[inline(always)]
pub fn initialize<A: Access>(a: &mut A) {
    if a.read_flags() & (1 << 14) != 0 {
        return;
    }
    let initial = (a.read_attenuation() as i8 as i32).max(0);
    a.calibrate(Output::Parameter(0x124), 0x14c, 128, initial, 0);
    a.calibrate(Output::Scratch, 0x162, 128, (initial - 20).max(0), 2);
    let flags = a.read_flags();
    a.write_flags(flags | (1 << 14));
}

#[inline(always)]
pub fn bluetooth<A: Access>(a: &mut A) {
    if a.read_flags() & (1 << 11) != 0 {
        return;
    }
    let (host, read_slot, write_slot) = if A::S3 {
        (0, 0x188, 0x190)
    } else {
        (1, 0x1ac, 0x1b4)
    };
    let table = a.table();
    let callback = a.slot(table, read_slot);
    let first = a.read_analog(callback, 103, host, 28);
    let table = a.table();
    let callback = a.slot(table, read_slot);
    let second = a.read_analog(callback, 103, host, 29);
    let table = a.table();
    let callback = a.slot(table, write_slot);
    a.write_analog(callback, 103, host, 28, 0);
    let table = a.table();
    let callback = a.slot(table, write_slot);
    a.write_analog(callback, 103, host, 29, 0);
    let code = a.read_attenuation();
    let code = if A::S3 { code } else { code.wrapping_add(20) } as i8 as i32;
    a.calibrate(Output::Parameter(0x182), 0x180, 32, code, 1);
    let flags = a.read_flags();
    let table;
    if A::S3 {
        a.write_flags(flags | (1 << 11));
        table = a.table();
    } else {
        table = a.table();
        a.write_flags(flags | (1 << 11));
    }
    let callback = a.slot(table, write_slot);
    a.write_analog(callback, 103, host, 28, first);
    let table = a.table();
    let callback = a.slot(table, write_slot);
    a.write_analog(callback, 103, host, 29, second);
}

#[cfg(all(not(test), any(target_arch = "xtensa", target_arch = "riscv32")))]
include!("phy_txiq_wrappers_native.rs");
