//! Analog I2C setup, preserving the chip-specific state and callback ordering.
//! The retained PHY owns calibration policy and serialization.

pub(crate) trait Access {
    type Table: Copy;
    type Function: Copy;
    unsafe fn read8(offset: usize) -> u8;
    unsafe fn write8(offset: usize, value: u8);
    #[cfg(esp32c3)]
    unsafe fn write16(offset: usize, value: u16);
    #[cfg(esp32c3)]
    unsafe fn write32(offset: usize, value: u32);
    unsafe fn table() -> Self::Table;
    unsafe fn slot(table: Self::Table, offset: usize) -> Self::Function;
    unsafe fn read_reg(function: Self::Function, block: u32, host: u32, reg: u32) -> u32;
    unsafe fn write_reg(function: Self::Function, block: u32, host: u32, reg: u32, data: u32);
    unsafe fn write_mask(function: Self::Function, args: [u32; 6]);
    #[cfg(esp32c3)]
    unsafe fn direct_bias(arg: u32);
    #[cfg(esp32c3)]
    unsafe fn direct_bias_part0();
}

#[cfg(esp32c3)]
const READ: usize = 0x1ac;
#[cfg(esp32s3)]
const READ: usize = 0x188;
#[cfg(esp32c3)]
const WRITE: usize = 0x1b4;
#[cfg(esp32s3)]
const WRITE: usize = 0x190;
#[cfg(esp32c3)]
const MASK: usize = 0x1bc;
#[cfg(esp32s3)]
const MASK: usize = 0x198;
#[cfg(esp32c3)]
const BBTOP_HOST: u32 = 1;
#[cfg(esp32s3)]
const BBTOP_HOST: u32 = 0;

#[inline(always)]
unsafe fn function<A: Access>(offset: usize) -> A::Function {
    unsafe { A::slot(A::table(), offset) }
}

#[inline(always)]
pub(crate) unsafe fn get_data<A: Access>() {
    unsafe {
        A::write8(0xbd, 27);
        #[cfg(esp32c3)]
        {
            A::write16(0xbe, 0x0877);
            A::write32(0xc0, 0x5f080aa4);
            A::write32(0xc4, 0x7f05740a);
            A::write32(0xc8, 0x3f02f000);
            A::write32(0xcc, 0x410ff3a8);
        }
        #[cfg(esp32s3)]
        {
            A::write8(0xbe, 119);
            let variant = A::read8(0x20d) == 1;
            A::write8(0xbf, if variant { 7 } else { 8 });
            for (offset, value) in [
                (0xc1, 10),
                (0xc4, 10),
                (0xc5, 116),
                (0xc6, 5),
                (0xc7, 127),
                (0xc8, 0),
                (0xc9, 240),
                (0xca, 2),
                (0xcb, 63),
                (0xcc, 168),
                (0xcd, 243),
                (0xce, 148),
            ] {
                A::write8(offset, value);
            }
            A::write8(0xc0, if variant { 148 } else { 164 });
            A::write8(0xcf, 68);
            A::write8(0xc2, 8);
            A::write8(0xc3, 95);
        }
        A::write8(0xd0, 38);
    }
}

#[inline(always)]
pub(crate) unsafe fn bias<A: Access>(arg: u32) {
    unsafe {
        #[cfg(esp32c3)]
        {
            if arg & 1 == 0 {
                A::direct_bias_part0();
                return;
            }
            A::direct_bias(0);
            if A::read8(0x9f) == 0 {
                let raw = A::read_reg(function::<A>(READ), 97, 0, 4);
                let value = (raw.wrapping_sub(15) as i16).max(60) as u8;
                A::write8(0x9f, value);
            }
            let table = A::table();
            let value = A::read8(0x9f);
            let writer = A::slot(table, WRITE);
            A::write8(0xa0, value);
            A::write_reg(writer, 97, 0, 6, value as u32);
            A::write_mask(function::<A>(MASK), [97, 0, 5, 6, 6, 1]);
        }
        #[cfg(esp32s3)]
        {
            let enabled = arg as u8 != 0;
            A::write_reg(
                function::<A>(WRITE),
                106,
                0,
                0,
                if enabled { 252 } else { 119 },
            );
            let writer = function::<A>(WRITE);
            let value = if !enabled {
                119
            } else if A::read8(0x20d) == 1 {
                127
            } else {
                124
            };
            A::write_reg(writer, 106, 0, 1, value);
        }
    }
}

#[inline(always)]
pub(crate) unsafe fn bbpll<A: Access>() {
    unsafe {
        for args in [
            [102, 0, 9, 3, 2, 3],
            [102, 0, 9, 5, 4, 2],
            [102, 0, 10, 1, 0, 1],
        ] {
            A::write_mask(function::<A>(MASK), args);
        }
        #[cfg(esp32c3)]
        A::write_mask(function::<A>(MASK), [102, 0, 4, 3, 2, 3]);
        let first = A::read_reg(function::<A>(READ), 102, 0, 9);
        let table = A::table();
        #[cfg(esp32s3)]
        let reader = A::slot(table, READ);
        A::write8(0xd1, first as u8);
        #[cfg(esp32c3)]
        let reader = A::slot(table, READ);
        let second = A::read_reg(reader, 102, 0, 10);
        #[cfg(esp32c3)]
        let gate = {
            let table = A::table();
            A::write8(0xd2, second as u8);
            let reader = A::slot(table, READ);
            let third = A::read_reg(reader, 102, 0, 4);
            let gate = A::read8(0x323);
            A::write8(0x31d, third as u8);
            gate
        };
        #[cfg(esp32s3)]
        let gate = {
            A::write8(0xd2, second as u8);
            A::read8(0x2a6)
        };
        if gate == 0 {
            A::write_mask(function::<A>(MASK), [102, 0, 5, 7, 7, 0]);
        }
        let last = A::read_reg(function::<A>(READ), 102, 0, 5);
        #[cfg(esp32c3)]
        A::write8(0x31e, last as u8);
        #[cfg(esp32s3)]
        A::write8(0x2a1, last as u8);
    }
}

#[inline(always)]
unsafe fn write_bbtop<A: Access>(reg: u32, value: u32) {
    unsafe { A::write_reg(function::<A>(WRITE), 103, BBTOP_HOST, reg, value) }
}

#[inline(always)]
unsafe fn write_param<A: Access>(reg: u32, offset: usize) {
    unsafe {
        let table = A::table();
        let value = A::read8(offset);
        let writer = A::slot(table, WRITE);
        A::write_reg(writer, 103, BBTOP_HOST, reg, value as u32);
    }
}

#[inline(always)]
pub(crate) unsafe fn init2<A: Access>() {
    unsafe {
        #[cfg(esp32c3)]
        let (reg29, reg31, reg22) = {
            let x = (A::read8(0x16d) as u32 + 10).min(60);
            let y = (A::read8(0x16e) as u32 + 3).min(60);
            let z = A::read8(0x16c).wrapping_add(4) as u32;
            (x, y, z)
        };
        #[cfg(esp32c3)]
        let reg55 = 85;
        #[cfg(esp32s3)]
        let reg55 = 0;
        for (reg, value) in [
            (36, 72),
            (40, 72),
            (37, 8),
            (41, 8),
            (44, 136),
            (48, 136),
            (45, 136),
            (49, 136),
            (52, 17),
            (53, 17),
            (54, 0),
            (55, reg55),
        ] {
            write_bbtop::<A>(reg, value);
        }
        #[cfg(esp32c3)]
        {
            write_param::<A>(4, 0x167);
            write_param::<A>(5, 0x167);
        }
        #[cfg(esp32s3)]
        let reg29 = {
            let table = A::table();
            let value = A::read8(0x167);
            let writer = A::slot(table, WRITE);
            let x = A::read8(0x16d);
            A::write_reg(writer, 103, BBTOP_HOST, 4, value as u32);
            let writer = function::<A>(WRITE);
            let value = A::read8(0x167);
            A::write_reg(writer, 103, BBTOP_HOST, 5, value as u32);
            // The original subtracts in 16 bits before an unsigned minimum
            // check; values below ten intentionally wrap, then narrow to u8.
            (x as u16).wrapping_sub(10).max(5) as u8 as u32
        };
        for (reg, offset) in [
            (12, 0x168),
            (13, 0x168),
            (6, 0x169),
            (7, 0x169),
            (14, 0x16a),
            (15, 0x16a),
            (20, 0x16b),
            (21, 0x16b),
        ] {
            write_param::<A>(reg, offset);
        }
        write_param::<A>(28, 0x16d);
        write_bbtop::<A>(29, reg29);
        #[cfg(esp32c3)]
        {
            write_bbtop::<A>(22, reg22);
            write_bbtop::<A>(23, reg22);
        }
        #[cfg(esp32s3)]
        {
            write_param::<A>(22, 0x16c);
            write_param::<A>(23, 0x16c);
        }
        write_param::<A>(30, 0x16e);
        #[cfg(esp32c3)]
        write_bbtop::<A>(31, reg31);
        #[cfg(esp32s3)]
        write_param::<A>(31, 0x16e);
        write_bbtop::<A>(56, 255);
        A::write_mask(function::<A>(MASK), [103, BBTOP_HOST, 2, 3, 2, 1]);
        A::write_reg(function::<A>(WRITE), 98, 1, 0, 168);
        #[cfg(esp32c3)]
        let value = 104;
        #[cfg(esp32s3)]
        let value = 72;
        A::write_reg(function::<A>(WRITE), 98, 1, 11, value);
        A::write_reg(function::<A>(WRITE), 98, 1, 2, 136);
    }
}

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
        fn bias_dreg_i2c_set(arg: u32);
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
        unsafe fn write8(offset: usize, value: u8) {
            unsafe {
                (&raw mut phy_param)
                    .cast::<u8>()
                    .add(offset)
                    .write_volatile(value)
            }
        }
        #[cfg(esp32c3)]
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
        #[cfg(esp32c3)]
        #[inline(always)]
        unsafe fn write32(offset: usize, value: u32) {
            unsafe {
                (&raw mut phy_param)
                    .cast::<u8>()
                    .add(offset)
                    .cast::<u32>()
                    .write_volatile(value)
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
        #[inline(always)]
        unsafe fn read_reg(function: Self::Function, block: u32, host: u32, reg: u32) -> u32 {
            #[cfg(esp32c3)]
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32, u32) -> u32>(function)(
                    block, host, reg,
                )
            }
            #[cfg(esp32s3)]
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u8, u8, u8) -> u32>(function)(
                    block as u8,
                    host as u8,
                    reg as u8,
                )
            }
        }
        #[inline(always)]
        unsafe fn write_reg(function: Self::Function, block: u32, host: u32, reg: u32, data: u32) {
            #[cfg(esp32c3)]
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32, u32, u32)>(function)(
                    block, host, reg, data,
                )
            }
            #[cfg(esp32s3)]
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u8, u8, u8, u8)>(function)(
                    block as u8,
                    host as u8,
                    reg as u8,
                    data as u8,
                )
            }
        }
        #[inline(always)]
        unsafe fn write_mask(function: Self::Function, args: [u32; 6]) {
            #[cfg(esp32c3)]
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32, u32, u32, u32, u32)>(
                    function,
                )(args[0], args[1], args[2], args[3], args[4], args[5])
            }
            #[cfg(esp32s3)]
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u8, u8, u8, u8, u8, u8)>(
                    function,
                )(
                    args[0] as u8,
                    args[1] as u8,
                    args[2] as u8,
                    args[3] as u8,
                    args[4] as u8,
                    args[5] as u8,
                )
            }
        }
        #[cfg(esp32c3)]
        #[inline(always)]
        unsafe fn direct_bias(arg: u32) {
            unsafe { bias_dreg_i2c_set(arg) }
        }
        #[cfg(esp32c3)]
        #[inline(always)]
        unsafe fn direct_bias_part0() {
            // The local part.0 symbol is not link-visible. The public entry
            // with argument one branches to that same retained implementation.
            unsafe { bias_dreg_i2c_set(1) }
        }
    }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_i2c_get_data() {
    unsafe { get_data::<native::Native>() }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_i2c_bias(arg: u32) {
    unsafe { bias::<native::Native>(arg) }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_i2c_bbpll() {
    unsafe { bbpll::<native::Native>() }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_i2c_init2() {
    unsafe { init2::<native::Native>() }
}
