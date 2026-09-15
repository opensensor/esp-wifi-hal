unsafe extern "C" {
    static mut phy_param: u8;
    static mut g_phyFuns: *const u8;
    fn txiq_set_reg(code: i32, select: u32) -> i32;
    fn txiq_get_mis_pwr(select: u32, attenuation: u32, tone: i32, out1: *mut u16, out2: *mut u16);
    fn txdc_cal_v70(buffer: *mut u16);
    fn get_power_atten(tone: i32, initial: i32, target: i32, offset: u32, debug: u32) -> i32;
    fn txcal_debuge_mode();
    fn txcal_work_mode();
    fn txiq_cover(attenuation: u32, tone: i32, out: *mut u8);
}
struct Hardware {
    samples: core::mem::MaybeUninit<[u16; 2]>,
    coefficients: core::mem::MaybeUninit<[u8; 2]>,
}
impl Hardware {
    #[inline(always)]
    fn new() -> Self {
        Self {
            samples: core::mem::MaybeUninit::uninit(),
            coefficients: core::mem::MaybeUninit::uninit(),
        }
    }
}
impl Access for Hardware {
    const S3: bool = cfg!(target_arch = "xtensa");
    #[inline(always)]
    fn read(&mut self, a: u32, w: usize) -> u32 {
        unsafe {
            match w {
                1 => core::ptr::read_volatile(a as *const u8) as u32,
                2 => core::ptr::read_volatile(a as *const u16) as u32,
                4 => core::ptr::read_volatile(a as *const u32),
                _ => unreachable!(),
            }
        }
    }
    #[inline(always)]
    fn write(&mut self, a: u32, w: usize, v: u32) {
        unsafe {
            match w {
                1 => core::ptr::write_volatile(a as *mut u8, v as u8),
                2 => core::ptr::write_volatile(a as *mut u16, v as u16),
                4 => core::ptr::write_volatile(a as *mut u32, v),
                _ => unreachable!(),
            }
        }
    }
    #[inline(always)]
    fn parameter(&mut self, o: usize, w: usize) -> u32 {
        self.read((&raw const phy_param) as u32 + o as u32, w)
    }
    #[inline(always)]
    fn table(&mut self) -> u32 {
        unsafe { core::ptr::read_volatile(&raw const g_phyFuns) as u32 }
    }
    #[inline(always)]
    fn slot(&mut self, t: u32, o: u32) -> u32 {
        unsafe { core::ptr::read_volatile((t + o) as *const u32) }
    }
    #[inline(always)]
    fn call1(&mut self, p: u32, a: u32) -> u32 {
        unsafe {
            let f: unsafe extern "C" fn(u32) -> u32 = core::mem::transmute(p);
            f(a)
        }
    }
    #[inline(always)]
    fn call2(&mut self, p: u32, a: u32, b: u32) -> u32 {
        unsafe {
            let f: unsafe extern "C" fn(u32, u32) -> u32 = core::mem::transmute(p);
            f(a, b)
        }
    }
    #[inline(always)]
    fn call3(&mut self, p: u32, a: u32, b: u32, c: u32) -> u32 {
        unsafe {
            let f: unsafe extern "C" fn(u32, u32, u32) -> u32 = core::mem::transmute(p);
            f(a, b, c)
        }
    }
    #[inline(always)]
    fn set_correction(&mut self, c: i32, s: u32) -> i32 {
        unsafe { txiq_set_reg(c, s) }
    }
    #[inline(always)]
    fn measure(&mut self, s: u32, a: u32, t: i32) {
        unsafe {
            let p = self.samples.as_mut_ptr().cast::<u16>();
            txiq_get_mis_pwr(s, a, t, p, p.add(1));
        }
    }
    #[inline(always)]
    fn sample(&mut self, i: usize) -> i16 {
        // Each preceding measurement initializes both aligned halfwords.
        unsafe { core::ptr::read_volatile(self.samples.as_ptr().cast::<u16>().add(i)) as i16 }
    }
    #[inline(always)]
    fn debug_mode(&mut self) {
        unsafe { txcal_debuge_mode() }
    }
    #[inline(always)]
    fn work_mode(&mut self) {
        unsafe { txcal_work_mode() }
    }
    #[inline(always)]
    fn txdc(&mut self, d: u32) {
        unsafe { txdc_cal_v70(d as *mut u16) }
    }
    #[inline(always)]
    fn attenuation(&mut self, t: i32, a: i32, p: i32, o: u32) -> i32 {
        unsafe { get_power_atten(t, a, p, o, 0) }
    }
    #[inline(always)]
    fn cover(&mut self, c: u8, t: i32) {
        unsafe { txiq_cover(c as u32, t, self.coefficients.as_mut_ptr().cast()) }
    }
    #[inline(always)]
    fn coefficient(&mut self, i: usize) -> u8 {
        // The preceding search initializes both coefficient bytes.
        unsafe { core::ptr::read_volatile(self.coefficients.as_ptr().cast::<u8>().add(i)) }
    }
    #[inline(always)]
    fn write_coefficient(&mut self, i: usize, v: u8) {
        unsafe { core::ptr::write_volatile(self.coefficients.as_mut_ptr().cast::<u8>().add(i), v) }
    }
}
#[unsafe(no_mangle)]
pub unsafe extern "C" fn __opensensor_txiq_search(attenuation: u32, tone: i32, out: u32) {
    // The caller supplies a writable two-byte output.
    search(&mut Hardware::new(), attenuation, tone, out)
}
#[unsafe(no_mangle)]
pub unsafe extern "C" fn __opensensor_txiq_calibrate(
    initial: u32,
    dc: u32,
    iq: u32,
    tone: u32,
    attenuation: u32,
    mode: u32,
) {
    // dc covers four aligned halfwords; iq is an aligned writable halfword.
    // The DC buffer is input for modes 0/1 and output for mode 2.
    calibrate(
        &mut Hardware::new(),
        initial,
        dc,
        iq,
        tone,
        attenuation,
        mode,
    )
}
