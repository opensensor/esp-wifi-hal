//! TX power-detector reference sequencing, preserving original access widths and order.
pub trait Access {
    const S3: bool;
    fn read_register(&mut self) -> u32;
    fn write_register(&mut self, value: u32);
    fn read_flags(&mut self) -> u32;
    fn write_flags(&mut self, value: u32);
    fn write_sample(&mut self, index: usize, value: u16);
    fn tone(&mut self, code: u8);
    fn sample(&mut self) -> u32;
    fn debug_mode(&mut self);
    fn work_mode(&mut self);
}

pub fn reference<A: Access>(io: &mut A, code: u8) {
    io.tone(code);
    let register = io.read_register();
    io.write_register(register & 0xffff_0000);
    let first = io.sample();
    let register = io.read_register();
    io.write_sample(0, first as u16);
    io.write_register((register & 0xffff_0000) | 0x5555);
    let second = io.sample();
    let register;
    if A::S3 {
        io.write_sample(1, second as u16);
        register = io.read_register();
    } else {
        register = io.read_register();
        io.write_sample(1, second as u16);
    }
    io.write_register((register & 0xffff_0000) | 0xaaaa);
}

pub fn calibrate<A: Access>(io: &mut A) {
    if io.read_flags() & (1 << 24) != 0 {
        return;
    }
    io.debug_mode();
    reference(io, if A::S3 { 80 } else { 120 });
    io.work_mode();
    let flags = io.read_flags();
    io.write_flags(flags | (1 << 24));
}

#[cfg(all(not(test), any(target_arch = "xtensa", target_arch = "riscv32")))]
include!("phy_tx_detector_native.rs");
