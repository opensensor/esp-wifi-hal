//! Temperature measurement/range selection for the pinned C3/S3 PHY layout.
//! Analog conversion, sensor power/init and the attribute table remain vendor code.

pub(crate) trait Access {
    type Table: Copy;
    type Function: Copy;
    unsafe fn read8(offset: usize) -> u8;
    unsafe fn write8(offset: usize, value: u8);
    unsafe fn write16(offset: usize, value: u16);
    unsafe fn attribute8(offset: usize) -> u8;
    unsafe fn attribute16(offset: usize) -> u16;
    unsafe fn table() -> Self::Table;
    unsafe fn slot(table: Self::Table, offset: usize) -> Self::Function;
    unsafe fn call(function: Self::Function, args: [u32; 6]) -> u32;
}

#[cfg(esp32c3)]
const READ_DAC: usize = 0x1ac;
#[cfg(esp32s3)]
const READ_DAC: usize = 0x188;
#[cfg(esp32c3)]
const READ_CODE: usize = 0x208;
#[cfg(esp32s3)]
const READ_CODE: usize = 0x1e4;
#[cfg(esp32c3)]
const CONVERT: usize = 0x218;
#[cfg(esp32s3)]
const CONVERT: usize = 0x1f4;
#[cfg(esp32c3)]
const WRITE_DAC: usize = 0x1bc;
#[cfg(esp32s3)]
const WRITE_DAC: usize = 0x198;

#[inline(always)]
pub(crate) fn decode(value: u32) -> u32 {
    #[cfg(esp32s3)]
    let value = value & 0xff;
    match value {
        5 => 0,
        7 => 1,
        15 => 2,
        11 => 3,
        10 => 4,
        _ => 5,
    }
}

#[inline(always)]
fn attribute_row(index: u32) -> usize {
    // Only five DAC settings have attribute rows. The original decoder's
    // sentinel 5 is not a sixth row. Reject it before accessing vendor data.
    assert!(
        index < 5,
        "PHY temperature DAC index outside attribute table"
    );
    index as usize * 6
}

#[inline(never)]
pub(crate) unsafe fn range<A: Access>(temperature: i32, index: u32) -> u32 {
    #[cfg(esp32s3)]
    let (temperature, index) = (temperature as i16 as i32, index & 0xff);
    let row = attribute_row(index);
    unsafe {
        let lower = A::attribute16(row + 2) as i16 as i32;
        if temperature >= lower {
            let upper = A::attribute16(row + 4) as i16 as i32;
            if temperature <= upper {
                return A::attribute8(row + 1) as u32;
            }
        }
        let dac = if temperature > 99 {
            5
        } else if temperature > 79 {
            7
        } else if temperature >= -9 {
            15
        } else if temperature >= -29 {
            11
        } else {
            10
        };
        let table = A::table();
        let function = A::slot(table, WRITE_DAC);
        A::call(function, [105, 0, 6, 3, 0, dac]);
        dac
    }
}

#[inline(never)]
pub(crate) unsafe fn inner<A: Access>() -> u32 {
    unsafe {
        let table = A::table();
        let function = A::slot(table, READ_DAC);
        let dac = A::call(function, [105, 0, 6, 0, 0, 0]);
        let index = decode(dac & 15);
        let table = A::table();
        // C3 loads the slot before the store; S3 loads it afterward.
        #[cfg(esp32c3)]
        let function = A::slot(table, READ_CODE);
        A::write8(0xaa, index as u8);
        #[cfg(esp32s3)]
        let function = A::slot(table, READ_CODE);
        let code = A::call(function, [0; 6]);
        let index = A::read8(0xaa);
        let row = attribute_row(index as u32);
        let table = A::table();
        let offset = A::attribute8(row) as i8 as i32 as u32;
        let function = A::slot(table, CONVERT);
        let temperature = A::call(function, [code, offset, 0, 0, 0, 0]);
        let index = A::read8(0xaa);
        range::<A>(temperature as i32, index as u32);
        temperature
    }
}

#[inline(always)]
pub(crate) unsafe fn forward<A: Access>() -> u32 {
    unsafe { inner::<A>() }
}

#[inline(always)]
pub(crate) unsafe fn outer<A: Access>() -> u32 {
    unsafe {
        let value = forward::<A>();
        A::write16(0x92, value as u16);
        value
    }
}

#[cfg(not(test))]
mod native {
    use super::{Access, CONVERT, READ_CODE, READ_DAC, WRITE_DAC};
    #[cfg(esp32c3)]
    const PARAM_SIZE: usize = 848;
    #[cfg(esp32s3)]
    const PARAM_SIZE: usize = 740;
    unsafe extern "C" {
        static mut phy_param: [u8; PARAM_SIZE];
        static mut g_phyFuns: *const u8;
        static phy_tsens_attribute: [u8; 30];
    }
    pub(super) struct Native;
    #[derive(Clone, Copy)]
    pub(super) struct Function {
        address: usize,
        slot: usize,
    }
    impl Access for Native {
        type Table = *const u8;
        type Function = Function;
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
        unsafe fn attribute8(offset: usize) -> u8 {
            unsafe {
                (&raw const phy_tsens_attribute)
                    .cast::<u8>()
                    .add(offset)
                    .read_volatile()
            }
        }
        #[inline(always)]
        unsafe fn attribute16(offset: usize) -> u16 {
            unsafe {
                (&raw const phy_tsens_attribute)
                    .cast::<u8>()
                    .add(offset)
                    .cast::<u16>()
                    .read_volatile()
            }
        }
        #[inline(always)]
        unsafe fn table() -> Self::Table {
            unsafe { (&raw const g_phyFuns).read_volatile() }
        }
        #[inline(always)]
        unsafe fn slot(table: Self::Table, offset: usize) -> Self::Function {
            Function {
                address: unsafe { table.add(offset).cast::<usize>().read_volatile() },
                slot: offset,
            }
        }
        #[inline(always)]
        unsafe fn call(function: Self::Function, args: [u32; 6]) -> u32 {
            unsafe {
                match function.slot {
                    // Public esp_rom_regi2c.h declarations; ROM API linker
                    // aliases resolve them to the same I2C table functions.
                    READ_DAC => {
                        core::mem::transmute::<usize, unsafe extern "C" fn(u8, u8, u8) -> u8>(
                            function.address,
                        )(args[0] as u8, args[1] as u8, args[2] as u8)
                            as u32
                    }
                    WRITE_DAC => {
                        core::mem::transmute::<usize, unsafe extern "C" fn(u8, u8, u8, u8, u8, u8)>(
                            function.address,
                        )(
                            args[0] as u8,
                            args[1] as u8,
                            args[2] as u8,
                            args[3] as u8,
                            args[4] as u8,
                            args[5] as u8,
                        );
                        0
                    }
                    // No public C declaration: preserve the register-width
                    // arguments/results established by callers and ROM code.
                    READ_CODE => core::mem::transmute::<usize, unsafe extern "C" fn() -> u32>(
                        function.address,
                    )(),
                    CONVERT => {
                        core::mem::transmute::<usize, unsafe extern "C" fn(u32, i32) -> i32>(
                            function.address,
                        )(args[0], args[1] as i32) as u32
                    }
                    _ => unreachable!("unknown temperature callback slot"),
                }
            }
        }
    }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_tsens_decode(value: u32) -> u32 {
    decode(value)
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_tsens_range(temperature: i32, index: u32) -> u32 {
    unsafe { range::<native::Native>(temperature, index) }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_tsens_inner() -> u32 {
    unsafe { inner::<native::Native>() }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_tsens_forward() -> u32 {
    unsafe { forward::<native::Native>() }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_tsens_outer() -> u32 {
    unsafe { outer::<native::Native>() }
}
