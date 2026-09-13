//! Sensor power, initialization and temperature tracking state for C3/S3.
//! The caller retains the original exclusive PHY access and calibration policy.

pub(crate) trait Access {
    type Table: Copy;
    type Function: Copy;
    unsafe fn read8(offset: usize) -> u8;
    unsafe fn read16(offset: usize) -> u16;
    unsafe fn write8(offset: usize, value: u8);
    unsafe fn write16(offset: usize, value: u16);
    unsafe fn read_register(address: usize) -> u32;
    unsafe fn write_register(address: usize, value: u32);
    #[cfg(esp32c3)]
    unsafe fn attribute8(offset: usize) -> u8;
    unsafe fn table() -> Self::Table;
    unsafe fn slot(table: Self::Table, offset: usize) -> Self::Function;
    #[cfg(esp32c3)]
    unsafe fn write_dac(function: Self::Function, dac: u8);
    #[cfg(esp32s3)]
    unsafe fn table_measure(function: Self::Function);
    #[cfg(esp32c3)]
    unsafe fn direct_measure();
}

#[cfg(esp32c3)]
const SENSOR: usize = 0x6004_0058;
#[cfg(esp32s3)]
const SENSOR: usize = 0x6000_8850;
#[cfg(esp32c3)]
const OFF_FLAG: usize = 0x31f;
#[cfg(esp32s3)]
const OFF_FLAG: usize = 0x2a2;

#[inline(always)]
pub(crate) unsafe fn power<A: Access>(enabled: u32) {
    unsafe {
        let old = A::read_register(SENSOR);
        #[cfg(esp32c3)]
        let new = (old & !(1 << 22)) | ((enabled & 1) << 22);
        #[cfg(esp32s3)]
        let new = (old & !(3 << 22)) | if enabled & 255 != 0 { 3 << 22 } else { 0 };
        A::write_register(SENSOR, new);
    }
}

#[inline(always)]
pub(crate) unsafe fn xpd<A: Access>() {
    unsafe {
        if A::read8(OFF_FLAG) == 0 {
            power::<A>(0);
        }
        A::write8(OFF_FLAG, 1);
    }
}

#[inline(always)]
pub(crate) unsafe fn read_init<A: Access>(set_dac: u32, index: u32) {
    unsafe {
        #[cfg(esp32c3)]
        {
            if set_dac != 0 {
                // Like the measurement path, an unsupported row is rejected
                // at its access. The unused index is unrestricted otherwise.
                assert!(
                    index < 5,
                    "PHY temperature init index outside attribute table"
                );
                let table = A::table();
                let function = A::slot(table, 0x1bc);
                let dac = A::attribute8(index as usize * 6 + 1);
                A::write_dac(function, dac);
            }
            let value = A::read_register(0x600c_0014);
            A::write_register(0x600c_0014, value | 0x400);
            let value = A::read_register(0x600c_001c);
            A::write_register(0x600c_001c, value & !0x400);
            let value = A::read_register(0x6004_005c);
            A::write_register(0x6004_005c, value | 0x8000);
            power::<A>(1);
        }
        #[cfg(esp32s3)]
        {
            let _ = (set_dac, index);
            let value = A::read_register(0x6000_8034);
            A::write_register(0x6000_8034, value | 0x0040_0000);
            let value = A::read_register(0x6000_8904);
            A::write_register(0x6000_8904, value | 0x8000_0000);
            let value = A::read_register(0x6000_8904);
            A::write_register(0x6000_8904, value | 0x2000_0000);
            power::<A>(1);
            let value = A::read_register(SENSOR);
            A::write_register(SENSOR, value & !0x0100_0000);
        }
    }
}

#[cfg(esp32s3)]
#[inline(always)]
pub(crate) unsafe fn code<A: Access>() -> u32 {
    unsafe {
        let value = A::read_register(SENSOR);
        A::write_register(SENSOR, value | 0x0100_0000);
        let value = A::read_register(SENSOR);
        A::write_register(SENSOR, value & !0x0100_0000);
        A::read_register(SENSOR) & 255
    }
}

#[inline(always)]
pub(crate) fn temp_to_power(current: u32, reference: u32, mode: u32) -> u32 {
    let delta = current.wrapping_sub(reference) as i16 as i32;
    #[cfg(esp32c3)]
    {
        let quotient = if mode != 0 {
            if delta > 0 { delta / 4 } else { delta / 5 }
        } else if delta > 0 {
            delta / 6
        } else {
            delta / 4
        };
        quotient as i8 as i32 as u32
    }
    #[cfg(esp32s3)]
    {
        let _ = mode;
        let mut quotient = if delta > 0 { delta / 5 } else { delta / 4 };
        // This comparison is on the wrapped signed byte, not the full
        // quotient. Preserve the original behavior beyond ordinary RF use.
        if delta <= 0 && (quotient as i8) < -12 {
            quotient -= 1;
        }
        quotient as u8 as u32
    }
}

#[inline(always)]
pub(crate) unsafe fn get_temp_init<A: Access>(initial: u32, update: u32) {
    unsafe {
        #[cfg(esp32c3)]
        {
            A::direct_measure();
            if A::read8(0x204) == 17 {
                let value = A::read16(0x20c);
                A::write16(0x210, value);
            } else if update != 0 {
                let value = A::read16(0x92);
                A::write16(0x210, value);
            }
            if initial != 0 {
                let value = A::read16(0x92);
                A::write16(0x212, value);
            }
            let value = A::read16(0x210);
            A::write16(0x96, value);
            let value = A::read16(0x212);
            A::write16(0x94, value);
            A::write16(0x214, value);
        }
        #[cfg(esp32s3)]
        {
            let _ = initial;
            let update = update & 255;
            let table = A::table();
            let function = A::slot(table, 0x258);
            A::table_measure(function);
            if A::read8(0x204) == 17 {
                let value = A::read16(0x206);
                A::write16(0x20a, value);
            } else if update != 0 {
                let value = A::read16(0x92);
                A::write16(0x20a, value);
            }
            let reference = A::read16(0x20a);
            let current = A::read16(0x92);
            A::write16(0x2c4, reference);
            A::write16(0x2c6, current);
            A::write16(0x96, reference);
            A::write16(0x94, current);
        }
    }
}

// Keep the exact five-row data, including little-endian signed limits. All
// consumers use the linker alias; the source object has explicit alignment.
#[repr(C, align(2))]
pub(crate) struct Attributes(pub(crate) [u8; 30]);
pub(crate) const ATTRIBUTE_BYTES: [u8; 30] = [
    254, 5, 50, 0, 125, 0, 255, 7, 20, 0, 100, 0, 0, 15, 246, 255, 80, 0, 1, 11, 226, 255, 50, 0,
    2, 10, 216, 255, 20, 0,
];
#[cfg(not(test))]
#[unsafe(no_mangle)]
static __opensensor_tsens_attribute: Attributes = Attributes(ATTRIBUTE_BYTES);

#[cfg(not(test))]
mod native {
    use super::Access;
    #[cfg(esp32c3)]
    const PARAM_SIZE: usize = 848;
    #[cfg(esp32s3)]
    const PARAM_SIZE: usize = 740;
    unsafe extern "C" {
        static mut phy_param: [u8; PARAM_SIZE];
        static mut g_phyFuns: *const u8;
        #[cfg(esp32c3)]
        fn rom1_tsens_temp_read() -> u32;
        #[cfg(esp32c3)]
        static phy_tsens_attribute: [u8; 30];
    }
    pub(super) struct Native;
    impl Access for Native {
        type Table = *const u8;
        type Function = usize;
        #[inline(always)]
        unsafe fn read8(offset: usize) -> u8 {
            unsafe {
                (&raw const phy_param)
                    .cast::<u8>()
                    .add(offset)
                    .read_volatile()
            }
        }
        #[inline(always)]
        unsafe fn read16(offset: usize) -> u16 {
            unsafe {
                (&raw const phy_param)
                    .cast::<u8>()
                    .add(offset)
                    .cast::<u16>()
                    .read_volatile()
            }
        }
        #[inline(always)]
        unsafe fn write8(offset: usize, value: u8) {
            unsafe {
                (&raw mut phy_param)
                    .cast::<u8>()
                    .add(offset)
                    .write_volatile(value)
            }
        }
        #[inline(always)]
        unsafe fn write16(offset: usize, value: u16) {
            unsafe {
                (&raw mut phy_param)
                    .cast::<u8>()
                    .add(offset)
                    .cast::<u16>()
                    .write_volatile(value)
            }
        }
        #[inline(always)]
        unsafe fn read_register(address: usize) -> u32 {
            unsafe { (address as *const u32).read_volatile() }
        }
        #[inline(always)]
        unsafe fn write_register(address: usize, value: u32) {
            unsafe { (address as *mut u32).write_volatile(value) }
        }
        #[cfg(esp32c3)]
        #[inline(always)]
        unsafe fn attribute8(offset: usize) -> u8 {
            unsafe {
                (&raw const phy_tsens_attribute)
                    .cast::<u8>()
                    .add(offset)
                    .read_volatile()
            }
        }
        #[inline(always)]
        unsafe fn table() -> Self::Table {
            unsafe { (&raw const g_phyFuns).read_volatile() }
        }
        #[inline(always)]
        unsafe fn slot(table: Self::Table, offset: usize) -> Self::Function {
            unsafe { table.add(offset).cast::<usize>().read_volatile() }
        }
        #[cfg(esp32c3)]
        #[inline(always)]
        unsafe fn write_dac(function: Self::Function, dac: u8) {
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u8, u8, u8, u8, u8, u8)>(
                    function,
                )(105, 0, 6, 3, 0, dac)
            }
        }
        #[cfg(esp32s3)]
        #[inline(always)]
        unsafe fn table_measure(function: Self::Function) {
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn() -> u32>(function)();
            }
        }
        #[cfg(esp32c3)]
        #[inline(always)]
        unsafe fn direct_measure() {
            unsafe {
                rom1_tsens_temp_read();
            }
        }
    }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_tsens_power(enabled: u32) {
    unsafe { power::<native::Native>(enabled) }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[esp_hal::ram]
unsafe extern "C" fn __opensensor_tsens_xpd() {
    unsafe { xpd::<native::Native>() }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_tsens_init(set_dac: u32, index: u32) {
    unsafe { read_init::<native::Native>(set_dac, index) }
}
#[cfg(all(not(test), esp32s3))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_tsens_code() -> u32 {
    unsafe { code::<native::Native>() }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
extern "C" fn __opensensor_tsens_temp_to_power(current: u32, reference: u32, mode: u32) -> u32 {
    temp_to_power(current, reference, mode)
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_tsens_get_init(initial: u32, update: u32) {
    unsafe { get_temp_init::<native::Native>(initial, update) }
}
