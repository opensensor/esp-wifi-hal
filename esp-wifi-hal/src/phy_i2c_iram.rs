//! Low-level analog I2C transactions and initial programming.
//! Exported entrypoints and their native constants must remain in RAM.

pub(crate) trait Access {
    type Table: Copy;
    type Function: Copy;
    unsafe fn read8(offset: usize) -> u8;
    #[cfg(esp32s3)]
    unsafe fn write8(offset: usize, value: u8);
    #[cfg(esp32s3)]
    unsafe fn input8(input: *const u8, index: usize) -> u8;
    unsafe fn read_register(address: u32) -> u32;
    unsafe fn write_register(address: u32, value: u32);
    unsafe fn table() -> Self::Table;
    unsafe fn slot(table: Self::Table, offset: usize) -> Self::Function;
    unsafe fn pause(function: Self::Function) -> u32;
    unsafe fn resume(function: Self::Function, token: u32);
    unsafe fn block_value(function: Self::Function, block: u32) -> u32;
    unsafe fn read_original(
        function: Self::Function,
        block: u32,
        mask: u32,
        host: u32,
        reg: u32,
    ) -> u32;
    unsafe fn read_reg(function: Self::Function, block: u32, host: u32, reg: u32) -> u32;
    unsafe fn write_reg(function: Self::Function, block: u32, host: u32, reg: u32, data: u32);
    #[cfg(esp32s3)]
    unsafe fn write_mask(function: Self::Function, args: [u32; 6]);
    unsafe fn read_mask(function: Self::Function, args: [u32; 5]) -> u32;
    unsafe fn batch(function: Self::Function, data_a: [u8; 10], data_b: [u8; 10]);
    unsafe fn enter();
    unsafe fn exit();
    unsafe fn init2();
    #[cfg(esp32c3)]
    unsafe fn sar2(arg: u32);
    #[cfg(esp32s3)]
    unsafe fn sar2(function: Self::Function, arg: u32);
}

// read mask, initial mask, host, pause, resume, original read, batch,
// readReg, writeReg, readMask, writeMask.
#[cfg(esp32c3)]
const SLOTS: [usize; 11] = [
    0x178, 0x17c, 0x180, 0x184, 0x188, 0x18c, 0x1a4, 0x1ac, 0x1b4, 0x1b8, 0x1bc,
];
#[cfg(esp32s3)]
const SLOTS: [usize; 11] = [
    0x154, 0x158, 0x15c, 0x160, 0x164, 0x168, 0x180, 0x188, 0x190, 0x194, 0x198,
];

#[inline(always)]
unsafe fn function<A: Access>(index: usize) -> A::Function {
    unsafe { A::slot(A::table(), SLOTS[index]) }
}

#[inline(always)]
pub(crate) unsafe fn hostid<A: Access>(block: u32) -> u32 {
    let index = block.wrapping_sub(98) & 255;
    let host = u32::from(index <= 9 && (1u32 << index) & 0x227 != 0);
    unsafe {
        let value = A::read_register(0x6000e048);
        A::write_register(0x6000e048, (value & 0xfffe000f) | 0x1fe00);
    }
    host
}

#[inline(always)]
pub(crate) unsafe fn read<A: Access>(block: u32, _host: u32, reg: u32) -> u32 {
    #[cfg(esp32s3)]
    let (block, reg) = (block & 255, reg & 255);
    unsafe {
        let token = A::pause(function::<A>(3));
        A::enter();
        let mask = A::block_value(function::<A>(0), block);
        let host = A::block_value(function::<A>(2), block);
        let value = A::read_original(function::<A>(5), block, mask, host, reg);
        A::exit();
        A::resume(function::<A>(4), token);
        value
    }
}

#[inline(always)]
pub(crate) unsafe fn write<A: Access>(block: u32, _host: u32, reg: u32, data: u32) {
    #[cfg(esp32s3)]
    let (block, reg, data) = (block & 255, reg & 255, data & 255);
    unsafe {
        let token = A::pause(function::<A>(3));
        A::enter();
        let host = A::block_value(function::<A>(2), block);
        let address = host.wrapping_add(0x18003800).wrapping_shl(2);
        A::write_register(
            address,
            block | reg.wrapping_shl(8) | data.wrapping_shl(16) | 0x05000000,
        );
        // The original transaction waits for the busy bit without a timeout.
        while A::read_register(address) & (1 << 25) != 0 {}
        A::exit();
        A::resume(function::<A>(4), token);
    }
}

#[cfg(esp32c3)]
#[inline(always)]
pub(crate) unsafe fn bias_part0<A: Access>() {
    unsafe {
        A::write_reg(function::<A>(8), 106, 0, 0, 204);
        A::write_reg(function::<A>(8), 106, 0, 1, 124);
    }
}

#[cfg(esp32c3)]
#[inline(always)]
pub(crate) unsafe fn bias_dreg<A: Access>(arg: u32) {
    unsafe {
        if arg != 0 {
            bias_part0::<A>();
        } else {
            A::write_reg(function::<A>(8), 106, 0, 0, 119);
            A::write_reg(function::<A>(8), 106, 0, 1, 119);
        }
    }
}

#[inline(always)]
pub(crate) unsafe fn wakeup<A: Access>() {
    #[cfg(esp32c3)]
    let host = 1;
    #[cfg(esp32s3)]
    let host = 0;
    unsafe {
        let first = A::read_reg(function::<A>(7), 103, host, 4);
        let second = A::read_reg(function::<A>(7), 103, host, 6);
        if first == 16 && second == 16 {
            A::init2();
        }
    }
}

#[cfg(esp32s3)]
#[inline(always)]
pub(crate) unsafe fn txcap<A: Access>(input: *const u8, rate: u32) {
    let rate = rate as u8;
    unsafe {
        let use_saved = A::read8(0x2cd) != 0;
        let mut selected = [0u8; 3];
        for (column, output) in selected.iter_mut().enumerate() {
            let mut a = A::input8(input, column);
            let mut b = A::input8(input, column + 3);
            let mut c = A::input8(input, column + 6);
            if use_saved {
                a = A::read8(0x2ce + column * 3);
                b = A::read8(0x2cf + column * 3);
                c = A::read8(0x2d0 + column * 3);
            }
            *output = if rate <= 3 {
                a
            } else if rate <= 8 {
                b
            } else {
                c
            };
        }
        A::write_mask(function::<A>(10), [107, 0, 1, 3, 0, selected[0] as u32]);
        let packed = ((selected[2] as i8 as i32).wrapping_shl(4) | selected[1] as i32) as u8;
        A::write_reg(function::<A>(8), 107, 0, 2, packed as u32);
        let previous = A::read8(0xbd);
        A::write8(0xbd, (previous & 0xf0) | selected[0]);
        A::write8(0xbe, packed);
    }
}

#[inline(always)]
pub(crate) unsafe fn init1<A: Access>() {
    unsafe {
        A::enter();
        let mut values = [0u8; 20];
        #[cfg(esp32c3)]
        for (index, value) in values.iter_mut().enumerate() {
            *value = A::read8(0xbd + index);
        }
        #[cfg(esp32s3)]
        {
            // Explicit reads keep the original order without an IRAM function
            // needing a flash-resident permutation table.
            macro_rules! read { ($($offset:expr),*) => { $(values[$offset - 0xbd] = A::read8($offset);)* }; }
            read!(
                0xc0, 0xbd, 0xc1, 0xc2, 0xbe, 0xbf, 0xc3, 0xc4, 0xc7, 0xc8, 0xc9, 0xc6, 0xca, 0xc5,
                0xcb, 0xcc, 0xcf, 0xd0, 0xce, 0xcd
            );
        }
        let mut data_a = [0u8; 10];
        let mut data_b = [0u8; 10];
        data_a.copy_from_slice(&values[..10]);
        data_b.copy_from_slice(&values[10..]);
        let mask = A::block_value(function::<A>(1), 107);
        let previous = A::read_register(0x6000e048);
        #[cfg(esp32c3)]
        let batch = function::<A>(6);
        A::write_register(0x6000e048, (previous & 0xfffe000f) | (mask & 0x1fff0));
        #[cfg(esp32s3)]
        let batch = function::<A>(6);
        A::batch(batch, data_a, data_b);
        let previous = A::read_register(0x6000e048);
        #[cfg(esp32s3)]
        let table = A::table();
        A::write_register(0x6000e048, (previous & 0xfffe000f) | 0x1fe00);
        #[cfg(esp32c3)]
        let table = A::table();
        let reader = A::slot(table, SLOTS[9]);
        if A::read_mask(reader, [105, 0, 4, 3, 0]) == 0 {
            #[cfg(esp32c3)]
            A::sar2(1400);
            #[cfg(esp32s3)]
            {
                let callback = A::slot(A::table(), 0x23c);
                A::sar2(callback, 1400);
            }
        }
        A::exit();
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
        fn phy_i2c_enter_critical();
        fn phy_i2c_exit_critical();
        fn phy_i2c_init2();
        #[cfg(esp32c3)]
        fn rom_i2c_sar2_init_code(arg: u32);
    }
    // Volatile copies place the callback's six original arrays on the stack
    // while guaranteeing the constant input reads are available without cache.
    #[esp_hal::ram]
    #[unsafe(no_mangle)]
    static __opensensor_i2c_program: [[u8; 10]; 4] = [
        [107; 10],
        [1, 2, 3, 4, 5, 6, 7, 8, 10, 11],
        [98, 98, 98, 98, 98, 98, 99, 100, 100, 103],
        [3, 8, 10, 9, 4, 0, 1, 8, 4, 2],
    ];
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
        #[cfg(esp32s3)]
        #[inline(always)]
        unsafe fn write8(offset: usize, value: u8) {
            unsafe {
                (&raw mut phy_param)
                    .cast::<u8>()
                    .add(offset)
                    .write_volatile(value)
            }
        }
        #[cfg(esp32s3)]
        #[inline(always)]
        unsafe fn input8(input: *const u8, index: usize) -> u8 {
            unsafe { input.add(index).read_volatile() }
        }
        #[inline(always)]
        unsafe fn read_register(address: u32) -> u32 {
            unsafe { (address as *const u32).read_volatile() }
        }
        #[inline(always)]
        unsafe fn write_register(address: u32, value: u32) {
            unsafe { (address as *mut u32).write_volatile(value) }
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
        unsafe fn pause(function: Self::Function) -> u32 {
            unsafe { core::mem::transmute::<usize, unsafe extern "C" fn() -> u32>(function)() }
        }
        #[inline(always)]
        unsafe fn resume(function: Self::Function, token: u32) {
            unsafe { core::mem::transmute::<usize, unsafe extern "C" fn(u32)>(function)(token) }
        }
        #[inline(always)]
        unsafe fn block_value(function: Self::Function, block: u32) -> u32 {
            #[cfg(esp32c3)]
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u32) -> u32>(function)(block)
            }
            #[cfg(esp32s3)]
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u8) -> u32>(function)(
                    block as u8,
                )
            }
        }
        #[inline(always)]
        unsafe fn read_original(
            function: Self::Function,
            block: u32,
            mask: u32,
            host: u32,
            reg: u32,
        ) -> u32 {
            #[cfg(esp32c3)]
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32, u32, u32) -> u32>(
                    function,
                )(block, mask, host, reg)
            }
            #[cfg(esp32s3)]
            // The caller passes the returned host word unchanged. The retained
            // ROM callee narrows it internally; installed host IDs are zero/one.
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u8, u32, u32, u8) -> u32>(
                    function,
                )(block as u8, mask, host, reg as u8)
            }
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
        #[cfg(esp32s3)]
        #[inline(always)]
        unsafe fn write_mask(function: Self::Function, args: [u32; 6]) {
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
        #[inline(always)]
        unsafe fn read_mask(function: Self::Function, args: [u32; 5]) -> u32 {
            #[cfg(esp32c3)]
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32, u32, u32, u32) -> u32>(
                    function,
                )(args[0], args[1], args[2], args[3], args[4])
            }
            #[cfg(esp32s3)]
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u8, u8, u8, u8, u8) -> u32>(
                    function,
                )(
                    args[0] as u8,
                    args[1] as u8,
                    args[2] as u8,
                    args[3] as u8,
                    args[4] as u8,
                )
            }
        }
        #[inline(always)]
        unsafe fn batch(function: Self::Function, data_a: [u8; 10], data_b: [u8; 10]) {
            unsafe {
                let program = (&raw const __opensensor_i2c_program).read_volatile();
                #[cfg(esp32c3)]
                core::mem::transmute::<
                    usize,
                    unsafe extern "C" fn(
                        *const u8,
                        *const u8,
                        *const u8,
                        *const u8,
                        *const u8,
                        *const u8,
                        u32,
                        u32,
                    ),
                >(function)(
                    program[0].as_ptr(),
                    program[1].as_ptr(),
                    data_a.as_ptr(),
                    program[2].as_ptr(),
                    program[3].as_ptr(),
                    data_b.as_ptr(),
                    10,
                    0,
                );
                #[cfg(esp32s3)]
                core::mem::transmute::<
                    usize,
                    unsafe extern "C" fn(
                        *const u8,
                        *const u8,
                        *const u8,
                        *const u8,
                        *const u8,
                        *const u8,
                        u8,
                        u8,
                    ),
                >(function)(
                    program[0].as_ptr(),
                    program[1].as_ptr(),
                    data_a.as_ptr(),
                    program[2].as_ptr(),
                    program[3].as_ptr(),
                    data_b.as_ptr(),
                    10,
                    0,
                );
            }
        }
        #[inline(always)]
        unsafe fn enter() {
            unsafe { phy_i2c_enter_critical() }
        }
        #[inline(always)]
        unsafe fn exit() {
            unsafe { phy_i2c_exit_critical() }
        }
        #[inline(always)]
        unsafe fn init2() {
            unsafe { phy_i2c_init2() }
        }
        #[cfg(esp32c3)]
        #[inline(always)]
        unsafe fn sar2(arg: u32) {
            unsafe { rom_i2c_sar2_init_code(arg) }
        }
        #[cfg(esp32s3)]
        #[inline(always)]
        unsafe fn sar2(function: Self::Function, arg: u32) {
            unsafe { core::mem::transmute::<usize, unsafe extern "C" fn(u32)>(function)(arg) }
        }
    }
}

#[cfg(not(test))]
#[unsafe(no_mangle)]
#[esp_hal::ram]
unsafe extern "C" fn __opensensor_i2c_enter() {}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[esp_hal::ram]
unsafe extern "C" fn __opensensor_i2c_exit() {}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[esp_hal::ram]
unsafe extern "C" fn __opensensor_i2c_hostid(block: u32) -> u32 {
    unsafe { hostid::<native::Native>(block) }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[esp_hal::ram]
unsafe extern "C" fn __opensensor_i2c_read(block: u32, host: u32, reg: u32) -> u32 {
    unsafe { read::<native::Native>(block, host, reg) }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[esp_hal::ram]
unsafe extern "C" fn __opensensor_i2c_write(block: u32, host: u32, reg: u32, data: u32) {
    unsafe { write::<native::Native>(block, host, reg, data) }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[esp_hal::ram]
unsafe extern "C" fn __opensensor_i2c_init1() {
    unsafe { init1::<native::Native>() }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
#[esp_hal::ram]
unsafe extern "C" fn __opensensor_i2c_wakeup() {
    unsafe { wakeup::<native::Native>() }
}
#[cfg(all(not(test), esp32c3))]
#[unsafe(no_mangle)]
#[esp_hal::ram]
unsafe extern "C" fn __opensensor_i2c_bias_dreg(arg: u32) {
    unsafe { bias_dreg::<native::Native>(arg) }
}
#[cfg(all(not(test), esp32s3))]
#[unsafe(no_mangle)]
#[esp_hal::ram]
unsafe extern "C" fn __opensensor_i2c_txcap(input: *const u8, rate: u32) {
    unsafe { txcap::<native::Native>(input, rate) }
}
