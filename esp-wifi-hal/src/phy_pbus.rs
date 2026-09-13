//! PBUS programming and calibration-mode transitions for C3/S3.
//! Callers retain the PHY lock, calibration policy and ROM callback table.

pub(crate) trait Access {
    type Table: Copy;
    type Function: Copy;
    unsafe fn read8(offset: usize) -> u8;
    unsafe fn read16(offset: usize) -> u16;
    unsafe fn write32(offset: usize, value: u32);
    unsafe fn read_register(address: usize) -> u32;
    unsafe fn write_register(address: usize, value: u32);
    unsafe fn table() -> Self::Table;
    unsafe fn slot(table: Self::Table, offset: usize) -> Self::Function;
    unsafe fn call_void0(function: Self::Function);
    unsafe fn call_clock(function: Self::Function, arg: u32);
    unsafe fn call_rx(function: Self::Function, arg: u32);
    unsafe fn call_void2(function: Self::Function, arg0: u32, arg1: u32);
    unsafe fn call_index(function: Self::Function, arg: u32) -> u32;
    unsafe fn call_param(function: Self::Function, offset: u32);
    unsafe fn direct_stop_tone(arg: u32);
    #[cfg(esp32c3)]
    unsafe fn delay_us(micros: u32);
}

#[cfg(esp32c3)]
const SLOTS: [usize; 8] = [0x50, 0x1d4, 0x1ec, 0xec, 0x1f0, 0xfc, 0x1e4, 0x1d8];
#[cfg(esp32s3)]
const SLOTS: [usize; 8] = [0x44, 0x1b0, 0x1c8, 0xdc, 0x1cc, 0xe8, 0x1c0, 0x1b4];

#[inline(always)]
unsafe fn function<A: Access>(slot: usize) -> A::Function {
    unsafe {
        let table = A::table();
        A::slot(table, slot)
    }
}

#[cfg(esp32c3)]
#[inline(always)]
pub(crate) unsafe fn force_mode<A: Access>(enabled: u32) {
    unsafe {
        if enabled != 0 {
            let value = A::read_register(0x6000_610c);
            A::write_register(0x6000_610c, value & !0x0800_0000);
            let value = A::read_register(0x6000_6104);
            A::write_register(0x6000_6104, value | 1);
        } else {
            let value = A::read_register(0x6000_6104);
            A::write_register(0x6000_6104, value & !1);
            let value = A::read_register(0x6000_610c);
            A::write_register(0x6000_610c, value | 0x0800_0000);
            if A::read_register(0x6002_600c) & 2 != 0 {
                A::delay_us(1);
                let value = A::read_register(0x6001_c02c);
                A::write_register(0x6001_c02c, (value & 0x00ff_ffff) | 0x3200_0000);
                let value = A::read_register(0x6001_c02c);
                A::write_register(0x6001_c02c, value | 0x0080_0000);
                A::delay_us(2);
                let value = A::read_register(0x6001_c02c);
                A::write_register(0x6001_c02c, value & !0x0080_0000);
            }
        }
    }
}

#[inline(always)]
pub(crate) unsafe fn debug_mode<A: Access>() {
    unsafe {
        #[cfg(esp32c3)]
        let index = A::read8(0xa3) as usize;
        #[cfg(esp32s3)]
        let index = A::read8(0x20c) as usize;
        // The original chips load these state fields in different orders.
        // In particular C3 fetches its first callback before the byte field.
        #[cfg(esp32s3)]
        let mode = A::read8(0x0e + index) as u32;
        let gain = A::read16(0x20 + index * 2) as u32;
        let clock = function::<A>(SLOTS[0]);
        #[cfg(esp32c3)]
        let mode = A::read8(0x0e + index) as u32;
        A::call_clock(clock, 1);
        A::call_void0(function::<A>(SLOTS[1]));
        A::call_void2(function::<A>(SLOTS[2]), mode, gain);
        let index = A::call_index(function::<A>(SLOTS[3]), gain);
        #[cfg(esp32s3)]
        let index = index & 0xffff;
        // This function only constructs the pointer. The retained callback
        // owns its interpretation; preserve the original wrapping arithmetic.
        let offset = 0x124u32.wrapping_add(index.wrapping_mul(8));
        A::call_param(function::<A>(SLOTS[4]), offset);
        A::call_void0(function::<A>(SLOTS[5]));
    }
}

#[inline(always)]
pub(crate) unsafe fn work_mode<A: Access>() {
    unsafe {
        A::direct_stop_tone(1);
        A::call_clock(function::<A>(SLOTS[0]), 0);
        A::call_rx(function::<A>(SLOTS[6]), 0);
        A::call_void0(function::<A>(SLOTS[7]));
    }
}

#[inline(always)]
pub(crate) unsafe fn save<A: Access>() {
    #[cfg(esp32c3)]
    const SAVED: usize = 0x328;
    #[cfg(esp32s3)]
    const SAVED: usize = 0x2ac;
    for index in 0..6 {
        unsafe {
            let value = A::read_register(0x6000_60e0 + index * 4);
            A::write32(SAVED + index * 4, value);
        }
    }
}

// Twelve consecutive PBUS programs: low and high half of each of six range
// registers. These words come from the linked original's constants and stack
// initialization, including the per-program modifications to shared arrays.
#[cfg(esp32c3)]
const PROGRAMS: [&[u32]; 12] = [
    &[0x0709ff, 0x1713ff, 0xf50000, 0xf60000],
    &[0x0401ff, 0x1401ff],
    &[
        0x0403ff, 0x14f9ff, 0x1801ff, 0x4801ff, 0xf00000, 0xf10000, 0xf20000, 0xf40000,
    ],
    &[0x0401ff, 0x1401ff],
    &[0x14f9ff, 0x44ffff, 0xf30000],
    &[0x4401ff, 0x5401ff],
    &[0x0709ff, 0x1717ff, 0xf50000, 0xf60000],
    &[0x0401ff, 0x1401ff],
    &[
        0x0403ff, 0x14fdff, 0x1801ff, 0x4801ff, 0xf00000, 0xf10000, 0xf20000, 0xf40000,
    ],
    &[0x0401ff, 0x1401ff],
    &[0x14fdff, 0x44ffff, 0xf30000],
    &[0x4401ff, 0x5401ff],
];
#[cfg(esp32s3)]
const PROGRAMS: [&[u32]; 12] = [
    &[0x0709ff, 0x1713ff, 0xf50000, 0xf60000],
    &[0x0401ff, 0x1801ff, 0x1401ff],
    &[
        0x0403ff, 0x14f9ff, 0x1801ff, 0x4801ff, 0xf00000, 0xf10000, 0xf20000, 0xf40000,
    ],
    &[0x0401ff, 0x1801ff, 0x1401ff],
    &[0x14f9ff, 0x44ffff, 0xf30000],
    &[0x4401ff, 0x5401ff],
    &[0x0709ff, 0x1717ff, 0xf50000, 0xf60000],
    &[0x0401ff, 0x1801ff, 0x1401ff],
    &[
        0x0403ff, 0x14f9ff, 0x1801ff, 0x4831ff, 0xf00000, 0xf10000, 0xf20000, 0xf40000,
    ],
    &[0x0401ff, 0x1801ff, 0x1401ff],
    &[0x14fdff, 0x44ffff, 0xf30000],
    &[0x4401ff, 0x5401ff],
];

#[inline(always)]
pub(crate) unsafe fn mem<A: Access>() {
    let mut start = 0u32;
    for (program_index, words) in PROGRAMS.iter().enumerate() {
        let end = start + words.len() as u32;
        let register = 0x6000_60e0 + (program_index / 2) * 4;
        let shift = (program_index % 2) * 16;
        unsafe {
            let value = A::read_register(register);
            let range = (((end - 1) << 8) | start) & 0xffff;
            A::write_register(register, (value & !(0xffff << shift)) | (range << shift));
            for (index, word) in words.iter().enumerate() {
                A::write_register(0x6000_60cc, *word);
                let value = A::read_register(0x6000_60c8);
                let address = ((start + index as u32 + 0x200) & 0x3ff) << 8;
                A::write_register(0x6000_60c8, (value & 0xfffc_00ff) | address);
                let value = A::read_register(0x6000_60c8);
                A::write_register(0x6000_60c8, value & 0xfffc_ffff);
            }
        }
        start = end;
    }
    unsafe { save::<A>() };
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
        fn stop_tx_tone(enabled: u32);
        #[cfg(esp32c3)]
        fn ets_delay_us(micros: u32);
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
        unsafe fn read_register(address: usize) -> u32 {
            unsafe { (address as *const u32).read_volatile() }
        }
        #[inline(always)]
        unsafe fn write_register(address: usize, value: u32) {
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
        unsafe fn call_void0(function: Self::Function) {
            unsafe { core::mem::transmute::<usize, unsafe extern "C" fn()>(function)() }
        }
        #[inline(always)]
        unsafe fn call_clock(function: Self::Function, arg: u32) {
            #[cfg(esp32c3)]
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u32)>(function)(arg)
            }
            #[cfg(esp32s3)]
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u8)>(function)(arg as u8)
            }
        }
        #[inline(always)]
        unsafe fn call_rx(function: Self::Function, arg: u32) {
            #[cfg(esp32c3)]
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u32)>(function)(arg)
            }
            #[cfg(esp32s3)]
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u16)>(function)(arg as u16)
            }
        }
        #[inline(always)]
        unsafe fn call_void2(function: Self::Function, arg0: u32, arg1: u32) {
            #[cfg(esp32c3)]
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u32, u32)>(function)(arg0, arg1)
            }
            #[cfg(esp32s3)]
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u16, u16)>(function)(
                    arg0 as u16,
                    arg1 as u16,
                )
            }
        }
        #[inline(always)]
        unsafe fn call_index(function: Self::Function, arg: u32) -> u32 {
            #[cfg(esp32c3)]
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u32) -> u32>(function)(arg)
            }
            #[cfg(esp32s3)]
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(u16) -> u32>(function)(
                    arg as u16,
                )
            }
        }
        #[inline(always)]
        unsafe fn call_param(function: Self::Function, offset: u32) {
            let pointer = (&raw const phy_param)
                .cast::<u8>()
                .wrapping_add(offset as usize)
                .cast::<u16>();
            unsafe {
                core::mem::transmute::<usize, unsafe extern "C" fn(*const u16)>(function)(pointer)
            }
        }
        #[inline(always)]
        unsafe fn direct_stop_tone(arg: u32) {
            unsafe { stop_tx_tone(arg) }
        }
        #[cfg(esp32c3)]
        #[inline(always)]
        unsafe fn delay_us(micros: u32) {
            unsafe { ets_delay_us(micros) }
        }
    }
}

#[cfg(all(not(test), esp32c3))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_pbus_force_mode(enabled: u32) {
    unsafe { force_mode::<native::Native>(enabled) }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_pbus_debug_mode() {
    unsafe { debug_mode::<native::Native>() }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_pbus_work_mode() {
    unsafe { work_mode::<native::Native>() }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_pbus_save() {
    unsafe { save::<native::Native>() }
}
#[cfg(not(test))]
#[unsafe(no_mangle)]
unsafe extern "C" fn __opensensor_pbus_mem() {
    unsafe { mem::<native::Native>() }
}
