unsafe extern "C" {
    static mut g_phyFuns: *const u8;
    fn start_tx_tone_step(a: u32, b: u32, c: u32, d: u32, e: u32, f: u32);
    fn ets_delay_us(delay: u32);
    fn txtone_linear_pwr() -> i32;
    fn get_power_db(offset: u32) -> i32;
    fn phy_printf(format: *const u8, ...);
}
#[unsafe(no_mangle)]
pub static __OPENSENSOR_TX_IQ_FORMAT: [u8; 30] = *b"%d, atten=%d, pwr=%d, %d, %d\n\0";
struct Hardware;
impl Access for Hardware {
    const S3: bool = cfg!(target_arch = "xtensa");
    #[inline(always)]
    fn read_register(&mut self, a: u32) -> u32 {
        unsafe { core::ptr::read_volatile(a as *const u32) }
    }
    #[inline(always)]
    fn write_register(&mut self, a: u32, v: u32) {
        unsafe { core::ptr::write_volatile(a as *mut u32, v) }
    }
    #[inline(always)]
    fn write_sample(&mut self, a: u32, v: u16) {
        unsafe { core::ptr::write_volatile(a as *mut u16, v) }
    }
    #[inline(always)]
    fn delay(&mut self) {
        unsafe { ets_delay_us(2) }
    }
    #[inline(always)]
    fn linear(&mut self) -> i32 {
        unsafe { txtone_linear_pwr() }
    }
    #[inline(always)]
    fn tone(&mut self, tone: i32, code: u8) {
        unsafe { start_tx_tone_step(1, tone as u32, code as u32, 0, 0, 0) }
    }
    #[inline(always)]
    fn power_db(&mut self, offset: u32) -> i32 {
        unsafe { get_power_db(offset) }
    }
    #[inline(always)]
    fn log(&mut self, i: i32, a: i32, s: i32, t: i32, d: i32) {
        unsafe { phy_printf(__OPENSENSOR_TX_IQ_FORMAT.as_ptr(), i, a, s, t, d) }
    }
    #[inline(always)]
    fn limit(&mut self, delta: i32) -> i32 {
        unsafe {
            // C3 reloads both the table and slot on every unconverged iteration.
            // Keep this boundary even though the initial ROM slot is a clamp.
            let table = core::ptr::read_volatile(&raw const g_phyFuns);
            let address = core::ptr::read_volatile((table as usize + 40) as *const u32);
            let f: unsafe extern "C" fn(i32, i32, i32) -> i32 = core::mem::transmute(address);
            f(delta, 20, -20)
        }
    }
}
#[unsafe(no_mangle)]
pub unsafe extern "C" fn __opensensor_txiq_measure(
    select: u32,
    negative: u32,
    offset: i32,
    out1: u32,
    out2: u32,
) {
    // The PHY caller owns two valid aligned halfwords; they may alias.
    measure(&mut Hardware, select, negative, offset, out1, out2)
}
#[unsafe(no_mangle)]
pub unsafe extern "C" fn __opensensor_txiq_attenuation(
    tone: i32,
    initial_attenuation: i32,
    target: i32,
    offset: u32,
    debug: u32,
) -> i32 {
    // Preserve word arguments/return; the model applies S3's entry narrowing.
    attenuation(
        &mut Hardware,
        tone,
        initial_attenuation,
        target,
        offset,
        debug,
    )
}
