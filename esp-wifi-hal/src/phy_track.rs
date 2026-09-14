//! Tracking helpers. Existing RF cadence, callback ownership and busy polling
//! remain unchanged; ROM and wider calibration helpers stay external.

pub(crate) trait Access {
    unsafe fn param() -> usize;
    unsafe fn read8(offset: usize) -> u8;
    unsafe fn read16(offset: usize) -> u16;
    unsafe fn read32(offset: usize) -> u32;
    unsafe fn write8(offset: usize, value: u8);
    unsafe fn write16(offset: usize, value: u16);
    unsafe fn write32(offset: usize, value: u32);
    unsafe fn busy() -> u32;
    unsafe fn table() -> usize;
    unsafe fn slot(table: usize, offset: usize) -> usize;
    unsafe fn read_call<const N: usize>(target: usize, args: [u32; N]) -> u32;
    unsafe fn write_call<const N: usize>(target: usize, args: [u32; N]);
    unsafe fn external(kind: u32, args: [u32; 4]) -> u32;
    unsafe fn internal(kind: u32, args: [u32; 3]);
    unsafe fn print(kind: u32, args: [u32; 4]);
}
const ABS: usize = if cfg!(esp32c3) { 0x100 } else { 0xec };
const READ: usize = if cfg!(esp32c3) { 0x1ac } else { 0x188 };
const WRITE: usize = if cfg!(esp32c3) { 0x1b4 } else { 0x190 };
const MASK_WRITE: usize = WRITE + 8;
const BUSY: usize = if cfg!(esp32c3) { 0x321 } else { 0x2a4 };
#[inline(always)]
fn argument(value: u32) -> u32 {
    if cfg!(esp32s3) {
        value as u8 as u32
    } else {
        value
    }
}
#[inline(always)]
unsafe fn signed16<A: Access>(offset: usize) -> u32 {
    unsafe { A::read16(offset) as i16 as i32 as u32 }
}
#[inline(always)]
unsafe fn target<A: Access>(offset: usize) -> usize {
    unsafe { A::slot(A::table(), offset) }
}

#[inline(always)]
pub(crate) unsafe fn wait<A: Access>() {
    unsafe {
        let mut observed = false;
        while A::busy() & (1 << 31) != 0 {
            observed = true;
        }
        if observed {
            A::external(0, [50, 0, 0, 0]);
        }
    }
}
#[inline(always)]
pub(crate) unsafe fn ulp_set<A: Access>(enabled: u32, value: u32) {
    unsafe {
        let (enabled, value) = (argument(enabled), argument(value));
        let table = A::table();
        if enabled == 0 {
            A::write_call(A::slot(table, WRITE), [97, 0, 6, value]);
            return;
        }
        let raw = A::read_call(A::slot(table, READ), [97, 0, 4]);
        A::write8(0x9f, raw as u8);
        A::write8(0xa0, raw as u8);
        A::write_call(target::<A>(WRITE), [97, 0, 6, raw]);
        A::write_call(target::<A>(MASK_WRITE), [97, 0, 5, 6, 6, 1]);
    }
}
#[inline(always)]
pub(crate) unsafe fn ulp_track<A: Access>(debug: u32) {
    unsafe {
        let debug = argument(debug);
        let current = A::read16(0x94);
        let reference = A::read16(if cfg!(esp32c3) { 0x212 } else { 0x2c6 });
        let delta = current.wrapping_sub(reference) as i16 as i32;
        let adjustment = if delta < 0 { delta / 6 } else { delta >> 3 };
        let raw = A::read_call(target::<A>(0x28), [adjustment as u32, 15, (-15i32) as u32]);
        let base = A::read8(0x9f);
        let old = A::read8(0xa0);
        let value = raw.wrapping_add(base.into()) as i16;
        if value != i16::from(old) {
            A::write8(0xa0, value as u8);
            A::internal(1, [0, value as u8 as u32, 0]);
        }
        if debug != 0 {
            let base = A::read8(0x9f);
            let current = A::read8(0xa0);
            A::print(0, [current.into(), base.into(), 0, 0]);
        }
    }
}
#[inline(always)]
pub(crate) unsafe fn pll_track<A: Access>(debug: u32) {
    unsafe {
        let debug = argument(debug);
        let (table, current, previous);
        #[cfg(esp32c3)]
        {
            previous = signed16::<A>(0x94);
            current = signed16::<A>(0x92);
            table = A::table();
        }
        #[cfg(esp32s3)]
        {
            table = A::table();
            current = signed16::<A>(0x92);
            previous = signed16::<A>(0x94);
        }
        let distance = A::read_call(A::slot(table, ABS), [current.wrapping_sub(previous)]);
        if distance as i32 <= 9 || A::read8(BUSY) != 0 {
            return;
        }
        A::write8(BUSY, 1);
        let table = A::table();
        A::write8(BUSY + 4, 0);
        A::write_call(
            A::slot(table, if cfg!(esp32c3) { 0x228 } else { 0x204 }),
            [],
        );
        A::internal(0, [0; 3]);
        let code = A::read8(0x9b);
        let correction = A::external(3, [code.into(), 1, 0, 0]);
        if debug != 0 {
            #[cfg(esp32c3)]
            {
                let previous = signed16::<A>(0x94);
                let current = signed16::<A>(0x92);
                A::print(1, [current, previous, correction, 0]);
            }
            #[cfg(esp32s3)]
            {
                let table = A::table();
                let previous = signed16::<A>(0x94);
                let callback = A::slot(table, 0x194);
                let current = signed16::<A>(0x92);
                let stage = A::read_call(callback, [107, 0, 4, 7, 4]);
                A::print(1, [current, previous, correction, stage]);
            }
        }
        let current = A::read16(0x92);
        A::write16(0x94, current);
        if A::read8(0x9f) != 0 {
            A::internal(2, [debug, 0, 0]);
        }
        A::write_call(target::<A>(if cfg!(esp32c3) { 0x224 } else { 0x200 }), []);
        A::write8(BUSY, 0);
    }
}
#[inline(always)]
pub(crate) unsafe fn power_track<A: Access>(radio: u32, apply: u32, debug: u32) {
    unsafe {
        let (radio, apply, debug) = (argument(radio), argument(apply), argument(debug));
        let baseline_offset = if radio == 0 && A::read8(0x204) == 1 {
            if cfg!(esp32c3) { 0x20c } else { 0x206 }
        } else if radio == 1 && A::read8(0x204) == 16 {
            if cfg!(esp32c3) { 0x20e } else { 0x208 }
        } else {
            if cfg!(esp32c3) { 0x210 } else { 0x2c4 }
        };
        let baseline = signed16::<A>(baseline_offset);
        #[cfg(esp32s3)]
        let current = signed16::<A>(0x92);
        let table = A::table();
        #[cfg(esp32c3)]
        let current = signed16::<A>(0x92);
        let distance = A::read_call(A::slot(table, ABS), [current.wrapping_sub(baseline)]);
        let threshold = if distance as i32 > 7 { 4 } else { 2 };
        let table = A::table();
        let (callback, current);
        #[cfg(esp32c3)]
        {
            current = signed16::<A>(0x92);
            callback = A::slot(table, 0x28);
        }
        #[cfg(esp32s3)]
        {
            callback = A::slot(table, 0x28);
        }
        let low = signed16::<A>(if radio == 0 { 0xae } else { 0xb2 });
        let high = signed16::<A>(if radio == 0 { 0xb0 } else { 0xb4 });
        #[cfg(esp32s3)]
        {
            current = signed16::<A>(0x92);
        }
        let converted = A::read_call(callback, [current, high, low]) as i16 as i32 as u32;
        let table = A::table();
        let previous = signed16::<A>(0x96);
        let distance = A::read_call(A::slot(table, ABS), [converted.wrapping_sub(previous)]);
        let code = if distance as i32 >= threshold {
            let raw = A::external(
                2,
                [
                    converted,
                    baseline,
                    if cfg!(esp32c3) { radio } else { 0 },
                    0,
                ],
            );
            if cfg!(esp32c3) { raw } else { raw as u8 as u32 }
        } else {
            let raw = A::read8(0x1fa);
            if cfg!(esp32c3) {
                raw as i8 as i32 as u32
            } else {
                raw.into()
            }
        };
        if apply == 0 {
            return;
        }
        let offset = if radio == 0 { 0x1fb } else { 0x1fc };
        let previous = A::read8(offset) as i8 as i32;
        let compare = if cfg!(esp32c3) {
            code as i32
        } else {
            code as i8 as i32
        };
        if previous == compare {
            return;
        }
        #[cfg(esp32c3)]
        {
            A::external(7, [1, 0, 0, 0]);
        }
        #[cfg(esp32s3)]
        {
            A::write_call(target::<A>(0x240), [1]);
        }
        let current = A::read16(0x92);
        A::write8(0x1fa, code as u8);
        A::write16(0x96, current);
        if radio != 0 {
            #[cfg(esp32c3)]
            {
                A::write8(0x1fc, code as u8);
                A::external(6, [0; 4]);
            }
            #[cfg(esp32s3)]
            {
                let table = A::table();
                A::write8(0x1fc, code as u8);
                A::write_call(A::slot(table, 0x270), [0]);
            }
        } else {
            #[cfg(esp32c3)]
            {
                let gain = A::read8(0x1f2);
                A::write8(0x1fb, code as u8);
                A::external(5, [gain.into(), 0, 0, 0]);
            }
            #[cfg(esp32s3)]
            {
                A::write8(0x1fb, code as u8);
                let table = A::table();
                let gain = A::read8(0x1f2);
                A::write_call(A::slot(table, 0x264), [gain.into(), 0]);
            }
        }
        if debug != 0 {
            #[cfg(esp32c3)]
            {
                let current = signed16::<A>(0x92);
                let power = A::read8(0x1fa) as i8 as i32 as u32;
                A::print(2, [power, current, baseline, 0]);
            }
            #[cfg(esp32s3)]
            {
                let wifi = A::read8(0x1fb) as i8 as i32 as u32;
                let bt = A::read8(0x1fc) as i8 as i32 as u32;
                let current = signed16::<A>(0x92);
                A::print(2, [bt, wifi, current, baseline]);
            }
        }
        #[cfg(esp32c3)]
        {
            A::external(7, [0; 4]);
        }
        #[cfg(esp32s3)]
        {
            A::write_call(target::<A>(0x240), [0]);
        }
    }
}
#[inline(always)]
pub(crate) unsafe fn offset<A: Access>() {
    unsafe {
        if A::read32(0x120) & (1 << 22) != 0 {
            return;
        }
        let voltage = A::external(1, [0; 4]);
        let adjustment = if voltage <= 3299 {
            let slot = if cfg!(esp32c3) { 0x118 } else { 0x104 };
            let first = A::read_call(target::<A>(slot), [voltage, 3]);
            let second = A::read_call(target::<A>(slot), [3300, 3]);
            let narrowed = first.wrapping_sub(second).wrapping_mul(2) as i8 as i32;
            ((narrowed + 2) >> 2) as u8
        } else {
            0
        };
        A::write32(0x200, (voltage << 16) | (u32::from(adjustment) << 8));
        let flags = A::read32(0x120);
        A::write32(0x120, flags | (1 << 22));
    }
}
#[cfg(esp32c3)]
#[inline(always)]
pub(crate) unsafe fn rfcal<A: Access>(debug: u32, threshold: u32) {
    unsafe {
        let previous = signed16::<A>(0x214);
        let current = signed16::<A>(0x92);
        let distance = A::read_call(target::<A>(ABS), [current.wrapping_sub(previous)]);
        if (distance as i32) < (threshold as i32) {
            return;
        }
        A::write_call(target::<A>(8), []);
        A::external(4, [(A::param() + 0x124) as u32, 15, 32, 0]);
        let gain = A::read8(0x1f2);
        A::external(5, [gain.into(), 0, 0, 0]);
        if debug != 0 {
            let previous = signed16::<A>(0x214);
            let current = signed16::<A>(0x92);
            A::print(3, [current, previous, 0, 0]);
        }
        let current = A::read16(0x92);
        A::write16(0x214, current);
        A::write_call(target::<A>(12), []);
    }
}
#[cfg(esp32s3)]
#[inline(always)]
pub(crate) unsafe fn radio_power<A: Access>(radio: u32, enabled: u32, debug: u32) {
    unsafe {
        A::write_call(
            target::<A>(0x268),
            [radio, enabled as u8 as u32, debug as u8 as u32],
        )
    }
}

#[cfg(not(test))]
mod native {
    use super::Access;
    unsafe extern "C" {
        static mut phy_param: u8;
        static mut g_phyFuns: *const u8;
        fn ets_delay_us(us: u32);
        fn __opensensor_debug_voltage() -> u32;
        // Resolve through the existing ABI alias so LTO preserves this call
        // boundary, including its position among volatile state accesses.
        #[cfg_attr(esp32c3, link_name = "rom2_temp_to_power1")]
        #[cfg_attr(esp32s3, link_name = "ram_temp_to_power")]
        fn temperature_to_power(current: u32, reference: u32, mode: u32) -> u32;
        #[cfg(esp32c3)]
        fn ram2_rfpll_cap_correct(code: u32, enabled: u32) -> u32;
        #[cfg(esp32s3)]
        fn rfpll_cap_correct(code: u32, enabled: u32) -> u32;
        #[cfg(esp32c3)]
        fn txdc_cal_init(destination: *mut u8, count: u32, scale: u32, mode: u32);
        #[cfg(esp32c3)]
        fn ram1_wifi_set_tx_gain(gain: u32, mode: u32);
        #[cfg(esp32c3)]
        fn rom1_bt_set_tx_gain(gain: u32);
        #[cfg(esp32c3)]
        fn rom_phy_bbpll_cal(enabled: u32);
        fn phy_printf(format: *const core::ffi::c_char, ...);
    }
    pub(super) struct Native;
    impl Access for Native {
        #[inline(always)]
        unsafe fn param() -> usize {
            (&raw const phy_param) as usize
        }
        #[inline(always)]
        unsafe fn read8(o: usize) -> u8 {
            unsafe { ((Self::param() + o) as *const u8).read_volatile() }
        }
        #[inline(always)]
        unsafe fn read16(o: usize) -> u16 {
            unsafe { ((Self::param() + o) as *const u16).read_volatile() }
        }
        #[inline(always)]
        unsafe fn read32(o: usize) -> u32 {
            unsafe { ((Self::param() + o) as *const u32).read_volatile() }
        }
        #[inline(always)]
        unsafe fn write8(o: usize, v: u8) {
            unsafe { ((Self::param() + o) as *mut u8).write_volatile(v) }
        }
        #[inline(always)]
        unsafe fn write16(o: usize, v: u16) {
            unsafe { ((Self::param() + o) as *mut u16).write_volatile(v) }
        }
        #[inline(always)]
        unsafe fn write32(o: usize, v: u32) {
            unsafe { ((Self::param() + o) as *mut u32).write_volatile(v) }
        }
        #[inline(always)]
        unsafe fn busy() -> u32 {
            unsafe { (0x6000e168 as *const u32).read_volatile() }
        }
        #[inline(always)]
        unsafe fn table() -> usize {
            unsafe { (&raw const g_phyFuns).read_volatile() as usize }
        }
        #[inline(always)]
        unsafe fn slot(table: usize, offset: usize) -> usize {
            unsafe { ((table + offset) as *const usize).read_volatile() }
        }
        #[inline(always)]
        unsafe fn read_call<const N: usize>(target: usize, a: [u32; N]) -> u32 {
            unsafe {
                match N {
                    1 => core::mem::transmute::<usize, unsafe extern "C" fn(u32) -> u32>(target)(
                        a[0],
                    ),
                    2 => core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32) -> u32>(
                        target,
                    )(a[0], a[1]),
                    3 => core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32, u32) -> u32>(
                        target,
                    )(a[0], a[1], a[2]),
                    5 => core::mem::transmute::<
                        usize,
                        unsafe extern "C" fn(u32, u32, u32, u32, u32) -> u32,
                    >(target)(a[0], a[1], a[2], a[3], a[4]),
                    _ => unreachable!(),
                }
            }
        }
        #[inline(always)]
        unsafe fn write_call<const N: usize>(target: usize, a: [u32; N]) {
            unsafe {
                match N {
                    0 => core::mem::transmute::<usize, unsafe extern "C" fn()>(target)(),
                    1 => core::mem::transmute::<usize, unsafe extern "C" fn(u32)>(target)(a[0]),
                    2 => core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32)>(target)(
                        a[0], a[1],
                    ),
                    3 => {
                        core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32, u32)>(target)(
                            a[0], a[1], a[2],
                        )
                    }
                    4 => core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32, u32, u32)>(
                        target,
                    )(a[0], a[1], a[2], a[3]),
                    6 => core::mem::transmute::<
                        usize,
                        unsafe extern "C" fn(u32, u32, u32, u32, u32, u32),
                    >(target)(a[0], a[1], a[2], a[3], a[4], a[5]),
                    _ => unreachable!(),
                }
            }
        }
        #[inline(always)]
        unsafe fn external(kind: u32, a: [u32; 4]) -> u32 {
            unsafe {
                match kind {
                    0 => {
                        ets_delay_us(a[0]);
                        0
                    }
                    1 => __opensensor_debug_voltage(),
                    2 => temperature_to_power(a[0], a[1], a[2]),
                    3 => {
                        #[cfg(esp32c3)]
                        {
                            ram2_rfpll_cap_correct(a[0], a[1])
                        }
                        #[cfg(esp32s3)]
                        {
                            rfpll_cap_correct(a[0], a[1])
                        }
                    }
                    #[cfg(esp32c3)]
                    4 => {
                        txdc_cal_init(a[0] as *mut u8, a[1], a[2], a[3]);
                        0
                    }
                    #[cfg(esp32c3)]
                    5 => {
                        ram1_wifi_set_tx_gain(a[0], a[1]);
                        0
                    }
                    #[cfg(esp32c3)]
                    6 => {
                        rom1_bt_set_tx_gain(a[0]);
                        0
                    }
                    #[cfg(esp32c3)]
                    7 => {
                        rom_phy_bbpll_cal(a[0]);
                        0
                    }
                    _ => unreachable!(),
                }
            }
        }
        #[inline(always)]
        unsafe fn internal(kind: u32, a: [u32; 3]) {
            unsafe {
                match kind {
                    0 => super::__opensensor_track_wait(),
                    1 => super::__opensensor_track_ulp_set(a[0], a[1]),
                    2 => super::__opensensor_track_ulp(a[0]),
                    _ => unreachable!(),
                }
            }
        }
        #[inline(always)]
        unsafe fn print(kind: u32, a: [u32; 4]) {
            unsafe {
                match kind {
                    0 => phy_printf(c"ulp:set=%d,init=%d\n".as_ptr(), a[0] as i32, a[1] as i32),
                    #[cfg(esp32c3)]
                    1 => phy_printf(
                        c"temp=%d,%d,delta=%d\n".as_ptr(),
                        a[0] as i32,
                        a[1] as i32,
                        a[2] as i32,
                    ),
                    #[cfg(esp32s3)]
                    1 => phy_printf(
                        c"temp=%d,%d,delta=%d,stg1=%d\n".as_ptr(),
                        a[0] as i32,
                        a[1] as i32,
                        a[2] as i32,
                        a[3] as i32,
                    ),
                    #[cfg(esp32c3)]
                    2 => phy_printf(
                        c"correct_power=%d,temp=%d %d\n".as_ptr(),
                        a[0] as i32,
                        a[1] as i32,
                        a[2] as i32,
                    ),
                    #[cfg(esp32s3)]
                    2 => phy_printf(
                        c"correct_power=%d,%d,temp=%d %d\n".as_ptr(),
                        a[0] as i32,
                        a[1] as i32,
                        a[2] as i32,
                        a[3] as i32,
                    ),
                    #[cfg(esp32c3)]
                    3 => phy_printf(c"cal:temp=%d,%d\n".as_ptr(), a[0] as i32, a[1] as i32),
                    _ => unreachable!(),
                }
            }
        }
    }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
unsafe extern "C" fn __opensensor_track_wait() {
    unsafe { wait::<native::Native>() }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
unsafe extern "C" fn __opensensor_track_ulp_set(enabled: u32, value: u32) {
    unsafe { ulp_set::<native::Native>(enabled, value) }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
unsafe extern "C" fn __opensensor_track_ulp(debug: u32) {
    unsafe { ulp_track::<native::Native>(debug) }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
unsafe extern "C" fn __opensensor_track_pll(debug: u32) {
    unsafe { pll_track::<native::Native>(debug) }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
unsafe extern "C" fn __opensensor_track_power(radio: u32, apply: u32, debug: u32) {
    unsafe { power_track::<native::Native>(radio, apply, debug) }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[inline(never)]
unsafe extern "C" fn __opensensor_track_offset() {
    unsafe { offset::<native::Native>() }
}
#[cfg(all(not(test), esp32c3))]
#[unsafe(no_mangle)]
#[inline(never)]
unsafe extern "C" fn __opensensor_track_rfcal(debug: u32, threshold: u32) {
    unsafe { rfcal::<native::Native>(debug, threshold) }
}
#[cfg(all(not(test), esp32s3))]
#[unsafe(no_mangle)]
#[inline(never)]
unsafe extern "C" fn __opensensor_track_wifi(enabled: u32, debug: u32) {
    unsafe { radio_power::<native::Native>(0, enabled, debug) }
}
#[cfg(all(not(test), esp32s3))]
#[unsafe(no_mangle)]
#[inline(never)]
unsafe extern "C" fn __opensensor_track_bt(enabled: u32, debug: u32) {
    unsafe { radio_power::<native::Native>(1, enabled, debug) }
}
