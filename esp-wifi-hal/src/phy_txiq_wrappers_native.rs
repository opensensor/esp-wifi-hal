unsafe extern "C" {
    static mut phy_param: u8;
    static mut g_phyFuns: *const u8;
    fn rfcal_txiq(
        first: u32,
        output1: *mut u16,
        output2: *mut u16,
        tone: u32,
        attenuation: i32,
        mode: u32,
    );
}

struct Hardware;
impl Access for Hardware {
    const S3: bool = cfg!(target_arch = "xtensa");
    #[inline(always)]
    fn read_flags(&mut self) -> u32 {
        unsafe { core::ptr::read_volatile((&raw const phy_param).add(0x120).cast()) }
    }
    #[inline(always)]
    fn write_flags(&mut self, value: u32) {
        unsafe { core::ptr::write_volatile((&raw mut phy_param).add(0x120).cast(), value) }
    }
    #[inline(always)]
    fn read_attenuation(&mut self) -> u8 {
        unsafe { core::ptr::read_volatile((&raw const phy_param).add(216)) }
    }
    #[inline(always)]
    fn table(&mut self) -> u32 {
        unsafe { core::ptr::read_volatile(&raw const g_phyFuns) as u32 }
    }
    #[inline(always)]
    fn slot(&mut self, table: u32, offset: u32) -> u32 {
        unsafe { core::ptr::read_volatile((table + offset) as *const u32) }
    }
    #[inline(always)]
    fn read_analog(&mut self, callback: u32, block: u32, host: u32, register: u32) -> u32 {
        unsafe {
            let f: unsafe extern "C" fn(u32, u32, u32) -> u32 = core::mem::transmute(callback);
            f(block, host, register)
        }
    }
    #[inline(always)]
    fn write_analog(&mut self, callback: u32, block: u32, host: u32, register: u32, value: u32) {
        unsafe {
            let f: unsafe extern "C" fn(u32, u32, u32, u32) = core::mem::transmute(callback);
            f(block, host, register, value)
        }
    }
    #[inline(always)]
    fn calibrate(
        &mut self,
        output1: Output,
        output2: usize,
        tone: u32,
        attenuation: i32,
        mode: u32,
    ) {
        // Mode 2 passes output1 through to txdc_cal_v70, which writes two
        // pairs of halfwords. The helper owns initialization of all eight bytes.
        let mut scratch = core::mem::MaybeUninit::<[u16; 4]>::uninit();
        unsafe {
            let first = match output1 {
                Output::Parameter(offset) => (&raw mut phy_param).add(offset).cast(),
                Output::Scratch => scratch.as_mut_ptr().cast(),
            };
            rfcal_txiq(
                0,
                first,
                (&raw mut phy_param).add(output2).cast(),
                tone,
                attenuation,
                mode,
            );
        }
    }
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn __opensensor_txiq_initialize() {
    initialize(&mut Hardware)
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn __opensensor_txiq_bluetooth() {
    bluetooth(&mut Hardware)
}
