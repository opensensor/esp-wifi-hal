unsafe extern "C" {
    static mut phy_param: u8;
    fn start_tx_tone_step(a: u32, b: u32, c: u32, d: u32, e: u32, f: u32);
    fn get_tone_sar_dout(count: u32) -> u32;
    fn txcal_debuge_mode();
    fn txcal_work_mode();
}

struct Hardware;
impl Access for Hardware {
    const S3: bool = cfg!(target_arch = "xtensa");
    #[inline(always)]
    fn read_register(&mut self) -> u32 {
        unsafe { core::ptr::read_volatile(0x6000e05c as *const u32) }
    }
    #[inline(always)]
    fn write_register(&mut self, value: u32) {
        unsafe { core::ptr::write_volatile(0x6000e05c as *mut u32, value) }
    }
    #[inline(always)]
    fn read_flags(&mut self) -> u32 {
        unsafe { core::ptr::read_volatile(((&raw const phy_param) as usize + 0x120) as *const u32) }
    }
    #[inline(always)]
    fn write_flags(&mut self, value: u32) {
        unsafe {
            core::ptr::write_volatile(((&raw mut phy_param) as usize + 0x120) as *mut u32, value)
        }
    }
    #[inline(always)]
    fn write_sample(&mut self, index: usize, value: u16) {
        unsafe {
            core::ptr::write_volatile(
                ((&raw mut phy_param) as usize + 218 + index * 2) as *mut u16,
                value,
            )
        }
    }
    #[inline(always)]
    fn tone(&mut self, code: u8) {
        unsafe { start_tx_tone_step(1, 128, code as u32, 0, 0, 0) }
    }
    #[inline(always)]
    fn sample(&mut self) -> u32 {
        unsafe { get_tone_sar_dout(4) }
    }
    #[inline(always)]
    fn debug_mode(&mut self) {
        unsafe { txcal_debuge_mode() }
    }
    #[inline(always)]
    fn work_mode(&mut self) {
        unsafe { txcal_work_mode() }
    }
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn __opensensor_tx_detector_reference(code: u32) {
    reference(&mut Hardware, code as u8);
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn __opensensor_tx_detector_calibrate() {
    calibrate(&mut Hardware);
}
