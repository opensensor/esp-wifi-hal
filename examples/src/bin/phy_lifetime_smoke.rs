#![no_std]
#![no_main]

use embassy_executor::Spawner;
use embassy_time::{Duration, Timer, with_timeout};
use esp_backtrace as _;
use esp_wifi_hal::prelude::*;
use examples::{common_init, embassy_init, wifi_init};
use log::info;

#[cfg(not(any(feature = "esp32c3", feature = "esp32s3")))]
compile_error!("The PHY lifetime probe has only been reviewed for C3 and S3");

/// Only read software state after guard release; peripheral clocks may be off.
unsafe fn sensor_off_flag() -> u8 {
    #[cfg(feature = "esp32c3")]
    const FLAG: usize = 0x31f;
    #[cfg(feature = "esp32s3")]
    const FLAG: usize = 0x2a2;
    #[cfg(feature = "esp32c3")]
    const PARAM_SIZE: usize = 848;
    #[cfg(feature = "esp32s3")]
    const PARAM_SIZE: usize = 740;
    unsafe extern "C" {
        static mut phy_param: [u8; PARAM_SIZE];
    }
    unsafe {
        (&raw const phy_param)
            .cast::<u8>()
            .add(FLAG)
            .read_volatile()
    }
}

unsafe fn inspect_sensor_lifecycle(cycle: u32) {
    unsafe extern "C" {
        static mut g_phyFuns: *const u8;
        fn phy_xpd_tsens();
        #[cfg(feature = "esp32c3")]
        fn phy_set_tsens_power(enabled: u32);
        #[cfg(feature = "esp32s3")]
        fn ram_temp_to_power(current: u32, reference: u32, mode: u32) -> u32;
        #[cfg(feature = "esp32s3")]
        fn ram_tsens_code_read() -> u32;
    }
    #[cfg(feature = "esp32c3")]
    let (address, mask, slot, expected) = (
        0x6004_0058usize,
        1u32 << 22,
        0x130,
        phy_set_tsens_power as *const () as usize,
    );
    #[cfg(feature = "esp32s3")]
    let (address, mask, slot, expected) = (
        0x6000_8850usize,
        3u32 << 22,
        0x144,
        ram_temp_to_power as *const () as usize,
    );
    unsafe {
        let table = (&raw const g_phyFuns).read_volatile();
        let callback = table.add(slot).cast::<usize>().read_volatile();
        assert_eq!(callback, expected, "Sensor lifecycle callback differs");
        #[cfg(feature = "esp32s3")]
        assert_eq!(
            table.add(0x1e4).cast::<usize>().read_volatile(),
            ram_tsens_code_read as *const () as usize
        );
        let power_bits = (address as *const u32).read_volatile() & mask;
        let off_flag = sensor_off_flag();
        info!(
            "stage=phy_sensor_lifecycle cycle={} off_flag={} power_bits={:#x} callback={:#x} shutdown={:#x}",
            cycle, off_flag, power_bits, callback, phy_xpd_tsens as *const () as usize
        );
    }
}

/// Check the PBUS program ranges after normal initialization, with the sole
/// PHY guard held. This probe never writes PBUS registers or calls calibration
/// mode helpers outside their original initialization sequence.
unsafe fn inspect_pbus(cycle: u32) {
    #[cfg(feature = "esp32c3")]
    const PARAM_SIZE: usize = 848;
    #[cfg(feature = "esp32s3")]
    const PARAM_SIZE: usize = 740;
    #[cfg(feature = "esp32c3")]
    const SAVED: usize = 0x328;
    #[cfg(feature = "esp32s3")]
    const SAVED: usize = 0x2ac;
    #[cfg(feature = "esp32c3")]
    const EXPECTED: [u32; 6] = [
        0x05040300, 0x0f0e0d06, 0x14131210, 0x1a191815, 0x2423221b, 0x29282725,
    ];
    #[cfg(feature = "esp32s3")]
    const EXPECTED: [u32; 6] = [
        0x06040300, 0x110f0e07, 0x16151412, 0x1d1b1a17, 0x2826251e, 0x2d2c2b29,
    ];
    unsafe extern "C" {
        static mut phy_param: [u8; PARAM_SIZE];
        static mut g_phyFuns: *const u8;
        fn set_pbus_mem();
        fn save_pbus_reg();
        fn txcal_debuge_mode();
        fn txcal_work_mode();
        #[cfg(feature = "esp32c3")]
        fn ram_pbus_force_mode(enabled: u32);
    }
    unsafe {
        let param = (&raw const phy_param).cast::<u8>();
        assert_ne!(
            param.add(0x120).cast::<u32>().read_volatile() & 0x10000,
            0,
            "PBUS initialization flag missing"
        );
        for (index, expected) in EXPECTED.iter().enumerate() {
            let saved = param.add(SAVED + index * 4).cast::<u32>().read_volatile();
            let register = ((0x600060e0 + index * 4) as *const u32).read_volatile();
            assert_eq!(saved, *expected, "Saved PBUS range differs");
            assert_eq!(register, saved, "Live PBUS range differs");
        }
        let table = (&raw const g_phyFuns).read_volatile();
        #[cfg(feature = "esp32c3")]
        let force = table.add(0x1c0).cast::<usize>().read_volatile();
        #[cfg(feature = "esp32c3")]
        assert_eq!(
            force, ram_pbus_force_mode as *const () as usize,
            "PBUS force callback differs"
        );
        #[cfg(feature = "esp32s3")]
        let force = table.add(0x19c).cast::<usize>().read_volatile();
        info!(
            "stage=phy_pbus cycle={} ranges_checked=6 force={:#x} mem={:#x} save={:#x} debug={:#x} work={:#x}",
            cycle,
            force,
            set_pbus_mem as *const () as usize,
            save_pbus_reg as *const () as usize,
            txcal_debuge_mode as *const () as usize,
            txcal_work_mode as *const () as usize
        );
    }
}

/// Read the I2C callback table after normal initialization. Do not trigger extra
/// analog transactions or alter the table while inspecting its installation.
unsafe fn inspect_i2c(cycle: u32) {
    unsafe extern "C" {
        static mut g_phyFuns: *const u8;
        #[cfg(feature = "esp32c3")]
        fn rom1_get_i2c_hostid(block: u32) -> u32;
        #[cfg(feature = "esp32c3")]
        fn rom1_chip_i2c_readReg(block: u32, host: u32, reg: u32) -> u32;
        #[cfg(feature = "esp32c3")]
        fn rom1_chip_i2c_writeReg(block: u32, host: u32, reg: u32, data: u32);
        #[cfg(feature = "esp32c3")]
        fn rom1_phy_i2c_init1();
        #[cfg(feature = "esp32s3")]
        fn ram_get_i2c_hostid(block: u32) -> u32;
        #[cfg(feature = "esp32s3")]
        fn ram_chip_i2c_readReg(block: u32, host: u32, reg: u32) -> u32;
        #[cfg(feature = "esp32s3")]
        fn ram_chip_i2c_writeReg(block: u32, host: u32, reg: u32, data: u32);
        #[cfg(feature = "esp32s3")]
        fn ram_phy_i2c_init1();
        #[cfg(feature = "esp32s3")]
        fn ram_set_txcap_reg(input: *const u8, rate: u32);
    }
    #[cfg(feature = "esp32c3")]
    let entries = [
        (0x180, rom1_get_i2c_hostid as *const () as usize),
        (0x190, rom1_chip_i2c_readReg as *const () as usize),
        (0x1b0, rom1_chip_i2c_writeReg as *const () as usize),
        (0x278, rom1_phy_i2c_init1 as *const () as usize),
    ];
    #[cfg(feature = "esp32s3")]
    let entries = [
        (0x15c, ram_get_i2c_hostid as *const () as usize),
        (0x16c, ram_chip_i2c_readReg as *const () as usize),
        (0x18c, ram_chip_i2c_writeReg as *const () as usize),
        (0x254, ram_phy_i2c_init1 as *const () as usize),
        (0x100, ram_set_txcap_reg as *const () as usize),
    ];
    for (slot, expected) in entries {
        let actual = unsafe {
            let table = (&raw const g_phyFuns).read_volatile();
            table.add(slot).cast::<usize>().read_volatile()
        };
        info!(
            "stage=phy_i2c cycle={} slot={:#x} actual={:#x} expected={:#x}",
            cycle, slot, actual, expected
        );
        assert_eq!(actual, expected, "I2C callback installation differs");
    }
}

/// Inspect the initialized temperature path with the sole PHY guard alive and
/// before starting a MAC driver or periodic tracking task. No table is patched.
unsafe fn inspect_temperature(cycle: u32) {
    #[cfg(feature = "esp32c3")]
    const SLOTS: [usize; 4] = [0x1ac, 0x208, 0x218, 0x1bc];
    #[cfg(feature = "esp32s3")]
    const SLOTS: [usize; 4] = [0x188, 0x1e4, 0x1f4, 0x198];
    #[cfg(feature = "esp32c3")]
    const PARAM_SIZE: usize = 848;
    #[cfg(feature = "esp32s3")]
    const PARAM_SIZE: usize = 740;
    unsafe extern "C" {
        static mut phy_param: [u8; PARAM_SIZE];
        static mut g_phyFuns: *const u8;
        fn phy_get_tsens_value() -> i32;
        #[cfg(feature = "esp32c3")]
        fn rom1_tsens_temp_read() -> u32;
        #[cfg(feature = "esp32s3")]
        fn ram_tsens_temp_read() -> u32;
    }
    unsafe {
        let table = (&raw const g_phyFuns).read_volatile();
        let mut callbacks = [0; 4];
        for (address, slot) in callbacks.iter_mut().zip(SLOTS) {
            *address = table.add(slot).cast::<usize>().read_volatile();
        }
        #[cfg(feature = "esp32c3")]
        let (outer_slot, expected_outer) = (0x27c, rom1_tsens_temp_read as *const () as usize);
        #[cfg(feature = "esp32s3")]
        let (outer_slot, expected_outer) = (0x258, ram_tsens_temp_read as *const () as usize);
        let outer = table.add(outer_slot).cast::<usize>().read_volatile();
        assert_eq!(
            outer, expected_outer,
            "Temperature callback installation differs"
        );
        #[cfg(feature = "esp32c3")]
        assert_eq!(
            table.add(0x210).cast::<usize>().read_volatile(),
            phy_get_tsens_value as *const () as usize
        );
        let read_dac =
            core::mem::transmute::<usize, unsafe extern "C" fn(u8, u8, u8) -> u8>(callbacks[0]);
        let dac = read_dac(105, 0, 6) & 15;
        assert!(
            [5, 7, 15, 11, 10].contains(&dac),
            "Unsupported live sensor DAC"
        );
        let temperature = phy_get_tsens_value();
        let index = (&raw const phy_param)
            .cast::<u8>()
            .add(0xaa)
            .read_volatile();
        assert!(index < 5);
        // The reviewed retained ROM conversion clamps to this range. This is
        // a consistency check, not an independent calibrated thermometer.
        assert!((-200..=250).contains(&temperature));
        info!(
            "stage=phy_temperature cycle={} dac={} index={} temperature={} outer={:#x} read={:#x} code={:#x} convert={:#x} write={:#x}",
            cycle,
            dac,
            index,
            temperature,
            outer,
            callbacks[0],
            callbacks[1],
            callbacks[2],
            callbacks[3]
        );
    }
}

/// Inspect API state after normal enable; no extra wakeup or calibration call.
unsafe fn inspect_api(cycle: u32) {
    #[cfg(feature = "esp32c3")]
    const PARAM_SIZE: usize = 848;
    #[cfg(feature = "esp32s3")]
    const PARAM_SIZE: usize = 740;
    unsafe extern "C" {
        static mut phy_param: [u8; PARAM_SIZE];
        fn phy_get_rf_cal_version() -> u32;
        fn phy_wakeup_init();
        fn phy_close_rf();
    }
    let (flags, version) = unsafe {
        (
            (&raw const phy_param)
                .cast::<u8>()
                .add(0x120)
                .cast::<u32>()
                .read_volatile(),
            phy_get_rf_cal_version(),
        )
    };
    #[cfg(feature = "esp32c3")]
    assert_eq!(version, 0x4d0);
    #[cfg(feature = "esp32s3")]
    assert_eq!(version, 0x2c7);
    if cycle > 1 {
        assert_ne!(flags & 0x20, 0, "API wakeup did not record initialization");
    }
    info!(
        "stage=phy_api cycle={} flags={:#x} calibration_version={} wakeup={:#x} close={:#x}",
        cycle,
        flags,
        version,
        phy_wakeup_init as *const () as usize,
        phy_close_rf as *const () as usize
    );
}

/// Observe selected basic helpers; exercise only the pure interpolation helper.
unsafe fn inspect_basic(cycle: u32) {
    unsafe extern "C" {
        #[cfg_attr(feature = "esp32c3", link_name = "rom1_i2c_master_reset")]
        #[cfg_attr(feature = "esp32s3", link_name = "ram_i2c_master_reset")]
        fn basic_reset();
        fn chan14_mic_cfg();
        fn rom_set_chan_reg();
        #[cfg(feature = "esp32s3")]
        fn ram_set_chan_cal_interp(data: *const u8, channel: u32) -> u32;
    }
    let rom = rom_set_chan_reg as *const () as usize;
    #[cfg(feature = "esp32c3")]
    assert_eq!(rom, 0x4000_1bec);
    #[cfg(feature = "esp32s3")]
    assert_eq!(rom, 0x4000_633c);
    #[cfg(feature = "esp32s3")]
    let (interpolation, checked) = {
        let data = [0x80, 0x7f, 0xfe];
        for (channel, expected) in [
            (0, 0),
            (1, 128),
            (6, 127),
            (7, 102),
            (11, 254),
            (12, 0),
            (257, 128),
        ] {
            assert_eq!(
                unsafe { ram_set_chan_cal_interp(data.as_ptr(), channel) },
                expected
            );
        }
        (ram_set_chan_cal_interp as *const () as usize, 7)
    };
    #[cfg(feature = "esp32c3")]
    let (interpolation, checked) = (0usize, 0);
    info!(
        "stage=phy_basic cycle={} reset={:#x} channel14={:#x} rom_channel={:#x} interpolation={:#x} checked={}",
        cycle,
        basic_reset as *const () as usize,
        chan14_mic_cfg as *const () as usize,
        rom,
        interpolation,
        checked
    );
}

/// Record selected entries and existing state without issuing extra RF operations.
unsafe fn inspect_feature(cycle: u32) {
    unsafe extern "C" {
        fn phy_dig_reg_backup();
        fn phy_freq_mem_backup();
        fn phy_set_most_tpw();
        fn phy_11p_set();
        fn rom_phy_dig_reg_backup();
        fn rom_phy_freq_mem_backup();
        #[cfg(feature = "esp32c3")]
        static mut phy_param: [u8; 848];
        #[cfg(feature = "esp32s3")]
        static mut phy_param: [u8; 740];
    }
    let dig = rom_phy_dig_reg_backup as *const () as usize;
    let freq = rom_phy_freq_mem_backup as *const () as usize;
    #[cfg(feature = "esp32c3")]
    assert_eq!((dig, freq), (0x40001c30, 0x40001c20));
    #[cfg(feature = "esp32s3")]
    assert_eq!((dig, freq), (0x40006408, 0x400063d8));
    let param = (&raw const phy_param).cast::<u8>();
    let power = unsafe { param.add(0x98).read_volatile() };
    let enabled = unsafe { param.add(0xef).read_volatile() };
    let narrow = unsafe { param.add(0xf0).read_volatile() };
    info!(
        "stage=phy_feature cycle={} dig={:#x} freq={:#x} power={:#x} mode={:#x} rom_dig={:#x} rom_freq={:#x} power_byte={} enabled={} narrow={}",
        cycle,
        phy_dig_reg_backup as *const () as usize,
        phy_freq_mem_backup as *const () as usize,
        phy_set_most_tpw as *const () as usize,
        phy_11p_set as *const () as usize,
        dig,
        freq,
        power,
        enabled,
        narrow
    );
}

/// Check pure IQ conversion and observe callbacks without additional analog sampling.
unsafe fn inspect_debug(cycle: u32) {
    unsafe extern "C" {
        fn get_iq_value(destination: *mut i8, packed: u32, selector: u32);
        fn get_bias_ref_code();
        fn phy_get_vdd33();
        static mut g_phyFuns: *const u8;
    }
    #[cfg(feature = "esp32c3")]
    let high_selector_first = 16;
    #[cfg(feature = "esp32s3")]
    let high_selector_first = -16;
    let cases = [
        (0, 0, [0, 0]),
        (0x3f, 1, [0, -1]),
        (0x420, 0, [-16, -32]),
        (0x420, 1, [16, -32]),
        (0x81f, 0, [0, 31]),
        (0x81f, 1, [-32, 31]),
        (0xffff, 0, [-1, -1]),
        (0xffff, 1, [-1, -1]),
        (0xffff0420, 0, [-16, -32]),
        (0x420, 256, [high_selector_first, -32]),
    ];
    for (packed, selector, expected) in cases {
        let mut buffer = [0x55i8; 4];
        unsafe { get_iq_value(buffer.as_mut_ptr().add(1), packed, selector) };
        assert_eq!(buffer, [0x55, expected[0], expected[1], 0x55]);
    }
    #[cfg(feature = "esp32c3")]
    let slots = [0x1bc, 0x150, 0x1d4, 0x1cc, 0x1d8];
    #[cfg(feature = "esp32s3")]
    let slots = [0x198, 0x12c, 0x1b0, 0x1a8, 0x1b4];
    for slot in slots {
        let table = unsafe { (&raw const g_phyFuns).read_volatile() };
        let target = unsafe { table.add(slot).cast::<usize>().read_volatile() };
        assert_ne!(target, 0);
        info!(
            "stage=phy_debug_slot cycle={} slot={:#x} target={:#x}",
            cycle, slot, target
        );
    }
    info!(
        "stage=phy_debug cycle={} iq={:#x} bias={:#x} voltage={:#x} checked={}",
        cycle,
        get_iq_value as *const () as usize,
        get_bias_ref_code as *const () as usize,
        phy_get_vdd33 as *const () as usize,
        cases.len()
    );
}

/// Check reference arithmetic and observe power-detector callbacks without tones.
unsafe fn inspect_pwdet(cycle: u32) {
    unsafe extern "C" {
        fn get_sar_sig_ref(input: u32, signal: *mut u16, reference: *mut u16);
        fn phy_set_pwdet_power();
        fn pwdet_tone_start();
        fn get_tone_sar_dout();
        fn get_fm_sar_dout();
        fn txtone_linear_pwr();
        fn get_power_db();
        #[cfg(feature = "esp32c3")]
        fn rom1_read_sar2_code();
        #[cfg(feature = "esp32c3")]
        fn ram_pkdet_vol_start();
        #[cfg(feature = "esp32s3")]
        fn ram_read_sar2_code();
        static mut g_phyFuns: *const u8;
        #[cfg(feature = "esp32c3")]
        static mut phy_param: [u8; 848];
        #[cfg(feature = "esp32s3")]
        static mut phy_param: [u8; 740];
    }
    let param = (&raw const phy_param).cast::<u8>();
    let baseline = unsafe { param.add(0xda).cast::<u16>().read_volatile() };
    let calibration = unsafe { param.add(0xdc).cast::<u16>().read_volatile() };
    #[cfg(feature = "esp32c3")]
    let adjustment = 40u32;
    #[cfg(feature = "esp32s3")]
    let adjustment = 50u32;
    let cases = [0, 1, 39, 40, 49, 50, 0x7fff, 0xffff, 0xfffffff0, u32::MAX];
    for input in cases {
        let adjusted = input.wrapping_add(adjustment) as u16;
        let signal = if adjusted >= baseline {
            adjusted.wrapping_sub(baseline)
        } else {
            0
        };
        let reference = if calibration >= baseline {
            calibration.wrapping_sub(baseline)
        } else {
            0
        };
        let mut output = [0x55aau16; 4];
        unsafe {
            get_sar_sig_ref(
                input,
                output.as_mut_ptr().add(1),
                output.as_mut_ptr().add(2),
            )
        };
        assert_eq!(output, [0x55aa, signal, reference, 0x55aa]);
    }
    #[cfg(feature = "esp32c3")]
    let slots = [0x144, 0x148, 0x14c, 0x118];
    #[cfg(feature = "esp32s3")]
    let slots = [0x120, 0x124, 0x128, 0x104];
    for slot in slots {
        let table = unsafe { (&raw const g_phyFuns).read_volatile() };
        let target = unsafe { table.add(slot).cast::<usize>().read_volatile() };
        assert_ne!(target, 0);
        info!(
            "stage=phy_pwdet_slot cycle={} slot={:#x} target={:#x}",
            cycle, slot, target
        );
    }
    #[cfg(feature = "esp32c3")]
    let read = rom1_read_sar2_code as *const () as usize;
    #[cfg(feature = "esp32s3")]
    let read = ram_read_sar2_code as *const () as usize;
    info!(
        "stage=phy_pwdet cycle={} reference={:#x} power={:#x} tone={:#x} samples={:#x} fm={:#x} linear={:#x} db={:#x} read={:#x} baseline={} calibration={} checked={}",
        cycle,
        get_sar_sig_ref as *const () as usize,
        phy_set_pwdet_power as *const () as usize,
        pwdet_tone_start as *const () as usize,
        get_tone_sar_dout as *const () as usize,
        get_fm_sar_dout as *const () as usize,
        txtone_linear_pwr as *const () as usize,
        get_power_db as *const () as usize,
        read,
        baseline,
        calibration,
        cases.len()
    );
    #[cfg(feature = "esp32c3")]
    info!(
        "stage=phy_pwdet_pkdet cycle={} start={:#x}",
        cycle, ram_pkdet_vol_start as *const () as usize
    );
}

/// Observe the normal RC calibration result, then exercise only its already-
/// calibrated early return. No extra measurement or analog programming is added.
unsafe fn inspect_analog(cycle: u32) {
    unsafe extern "C" {
        #[cfg(feature = "esp32c3")]
        static mut phy_param: [u8; 848];
        #[cfg(feature = "esp32s3")]
        static mut phy_param: [u8; 740];
        static mut g_phyFuns: *const u8;
        fn get_rc_dout(selector: u32) -> u32;
        fn rc_cal();
        #[cfg(feature = "esp32c3")]
        static mut wifi_ht20: u16;
        #[cfg(feature = "esp32c3")]
        static mut wifi_ht40: u16;
    }
    unsafe {
        let param = (&raw const phy_param).cast::<u8>();
        let flags = param.add(0x120).cast::<u32>().read_volatile();
        assert_ne!(
            flags & (1 << 23),
            0,
            "Normal RC calibration did not complete"
        );
        let mut codes = [0u8; 9];
        for (i, value) in codes.iter_mut().enumerate() {
            *value = param.add(0x166 + i).read_volatile();
        }
        assert!(codes[1..].iter().all(|v| (2..=63).contains(v)));
        rc_cal();
        assert_eq!(param.add(0x120).cast::<u32>().read_volatile(), flags);
        for (i, value) in codes.iter().enumerate() {
            assert_eq!(param.add(0x166 + i).read_volatile(), *value);
        }
        let mode_offset = if cfg!(feature = "esp32c3") {
            0x322
        } else {
            0x2a5
        };
        info!(
            "stage=phy_analog cycle={} measurement={:#x} calibrate={:#x} flags={:#x} selector={} mode={} codes={:?} early_return_unchanged=true",
            cycle,
            get_rc_dout as *const () as usize,
            rc_cal as *const () as usize,
            flags,
            param.add(0xf3).read_volatile(),
            param.add(mode_offset).read_volatile(),
            codes
        );
        let write = if cfg!(feature = "esp32c3") {
            0x1bc
        } else {
            0x198
        };
        for slot in [write - 4, write] {
            let table = (&raw const g_phyFuns).read_volatile();
            let target = table.add(slot).cast::<usize>().read_volatile();
            assert_ne!(target, 0);
            info!(
                "stage=phy_analog_slot cycle={} slot={:#x} target={:#x}",
                cycle, slot, target
            );
        }
        #[cfg(feature = "esp32c3")]
        info!(
            "stage=phy_analog_divisors cycle={} ht20={} ht40={} left={:#x} right={:#x}",
            cycle,
            (&raw const wifi_ht20).read_volatile(),
            (&raw const wifi_ht40).read_volatile(),
            (&raw const wifi_ht20) as usize,
            (&raw const wifi_ht40) as usize
        );
    }
}

/// Observe the installed tracking entry points and normal calibration state.
/// Only the completed offset path is called; no additional tracking is scheduled.
unsafe fn inspect_track(cycle: u32) {
    unsafe extern "C" {
        static mut phy_param: u8;
        static mut g_phyFuns: *const u8;
        fn txpwr_offset();
        #[cfg(feature = "esp32c3")]
        fn rom2_wait_hw_freq_busy();
        #[cfg(feature = "esp32c3")]
        fn rom2_ulp_ext_code_set(first: u32, second: u32);
        #[cfg(feature = "esp32c3")]
        fn rom2_ulp_code_track(debug: u32);
        #[cfg(feature = "esp32c3")]
        fn ram2_rfpll_cap_track(debug: u32);
        #[cfg(feature = "esp32c3")]
        fn rom1_txpwr_cal_track(radio: u32, apply: u32, debug: u32);
        #[cfg(feature = "esp32c3")]
        fn rfcal_track(first: u32, second: u32);
        #[cfg(feature = "esp32s3")]
        fn wait_hw_freq_busy();
        #[cfg(feature = "esp32s3")]
        fn ulp_ext_code_set(first: u32, second: u32);
        #[cfg(feature = "esp32s3")]
        fn ulp_code_track(debug: u32);
        #[cfg(feature = "esp32s3")]
        fn rfpll_cap_track(debug: u32);
        #[cfg(feature = "esp32s3")]
        fn ram_txpwr_cal_track(radio: u32, apply: u32, debug: u32);
        #[cfg(feature = "esp32s3")]
        fn ram_wifi_track_tx_power(first: u32, second: u32);
        #[cfg(feature = "esp32s3")]
        fn ram_bt_track_tx_power(first: u32, second: u32);
    }
    unsafe {
        let param = (&raw const phy_param).cast::<u8>();
        let flags = param.add(0x120).cast::<u32>().read_volatile();
        assert_ne!(
            flags & (1 << 22),
            0,
            "Normal voltage offset did not complete"
        );
        let packed = param.add(0x200).cast::<u32>().read_volatile();
        txpwr_offset();
        assert_eq!(param.add(0x120).cast::<u32>().read_volatile(), flags);
        assert_eq!(param.add(0x200).cast::<u32>().read_volatile(), packed);
        let current = param.add(0x92).cast::<i16>().read_volatile();
        let previous = param.add(0x94).cast::<i16>().read_volatile();
        let power_previous = param.add(0x96).cast::<i16>().read_volatile();
        info!(
            "stage=phy_track cycle={} flags={:#x} packed={:#x} current={} previous={} power_previous={} ulp_base={} ulp_current={} early_return_unchanged=true",
            cycle,
            flags,
            packed,
            current,
            previous,
            power_previous,
            param.add(0x9f).read_volatile(),
            param.add(0xa0).read_volatile()
        );
        #[cfg(feature = "esp32c3")]
        let entries = [
            (0, rom2_wait_hw_freq_busy as *const () as usize),
            (1, rom2_ulp_ext_code_set as *const () as usize),
            (2, rom2_ulp_code_track as *const () as usize),
            (3, ram2_rfpll_cap_track as *const () as usize),
            (4, rom1_txpwr_cal_track as *const () as usize),
            (5, txpwr_offset as *const () as usize),
            (6, rfcal_track as *const () as usize),
        ];
        #[cfg(feature = "esp32s3")]
        let entries = [
            (0, wait_hw_freq_busy as *const () as usize),
            (1, ulp_ext_code_set as *const () as usize),
            (2, ulp_code_track as *const () as usize),
            (3, rfpll_cap_track as *const () as usize),
            (4, ram_txpwr_cal_track as *const () as usize),
            (5, txpwr_offset as *const () as usize),
            (7, ram_wifi_track_tx_power as *const () as usize),
            (8, ram_bt_track_tx_power as *const () as usize),
        ];
        for (operation, address) in entries {
            info!(
                "stage=phy_track_entry cycle={} operation={} address={:#x}",
                cycle, operation, address
            );
        }
        #[cfg(feature = "esp32c3")]
        let slots = [
            0x100, 0x28, 0x1ac, 0x1b4, 0x1bc, 0x228, 0x224, 0x118, 0x8, 0xc,
        ];
        #[cfg(feature = "esp32s3")]
        let slots = [
            0xec, 0x28, 0x188, 0x190, 0x198, 0x204, 0x200, 0x194, 0x104, 0x240, 0x264, 0x270, 0x268,
        ];
        for slot in slots {
            let table = (&raw const g_phyFuns).read_volatile();
            let target = table.add(slot).cast::<usize>().read_volatile();
            assert_ne!(target, 0);
            info!(
                "stage=phy_track_slot cycle={} slot={:#x} target={:#x}",
                cycle, slot, target
            );
        }
    }
}

/// Check pure frequency arithmetic and observe entry points after normal calibration.
/// This probe does not start an additional calibration or program an RF register.
unsafe fn inspect_rfpll(cycle: u32) {
    unsafe extern "C" {
        static mut phy_param: u8;
        static mut g_phyFuns: *const u8;
        fn rfpll_set_freq(frequency: u32, selector: u32, offset: u32, out: *mut u8);
        #[cfg(feature = "esp32c3")]
        fn restart_cal();
        #[cfg(feature = "esp32c3")]
        fn write_rfpll_sdm();
        #[cfg(feature = "esp32c3")]
        fn wait_rfpll_cal_end();
        #[cfg(feature = "esp32c3")]
        fn correct_rfpll_offset();
        #[cfg(feature = "esp32c3")]
        fn rom2_write_pll_cap();
        #[cfg(feature = "esp32c3")]
        fn rom2_read_pll_cap();
        #[cfg(feature = "esp32c3")]
        fn ram2_rfpll_cap_correct();
        #[cfg(feature = "esp32c3")]
        fn rfpll_cap_init_cal();
        #[cfg(feature = "esp32c3")]
        fn set_rfpll_freq();
        #[cfg(feature = "esp32c3")]
        fn set_rf_freq_offset();
        #[cfg(feature = "esp32c3")]
        fn set_channel_rfpll_freq();
        #[cfg(feature = "esp32c3")]
        fn chip_v7_set_chan_misc();
        #[cfg(feature = "esp32c3")]
        fn chip_v7_set_chan();
        #[cfg(feature = "esp32c3")]
        fn chip_v7_set_chan_offset();
        #[cfg(feature = "esp32c3")]
        fn chip_v7_set_chan_ana();
        #[cfg(feature = "esp32s3")]
        fn restart_cal();
        #[cfg(feature = "esp32s3")]
        fn write_rfpll_sdm();
        #[cfg(feature = "esp32s3")]
        fn wait_rfpll_cal_end();
        #[cfg(feature = "esp32s3")]
        fn correct_rfpll_offset();
        #[cfg(feature = "esp32s3")]
        fn ram_write_pll_cap();
        #[cfg(feature = "esp32s3")]
        fn read_pll_cap();
        #[cfg(feature = "esp32s3")]
        fn rfpll_cap_correct();
        #[cfg(feature = "esp32s3")]
        fn rfpll_cap_init_cal();
        #[cfg(feature = "esp32s3")]
        fn set_rfpll_freq();
        #[cfg(feature = "esp32s3")]
        fn set_rf_freq_offset();
        #[cfg(feature = "esp32s3")]
        fn set_channel_rfpll_freq();
        #[cfg(feature = "esp32s3")]
        fn chip_v7_set_chan_misc();
        #[cfg(feature = "esp32s3")]
        fn chip_v7_set_chan();
        #[cfg(feature = "esp32s3")]
        fn chip_v7_set_chan_offset();
        #[cfg(feature = "esp32s3")]
        fn chip_v7_set_chan_ana();
        #[cfg(feature = "esp32s3")]
        fn phy_set_freq();
        #[cfg(feature = "esp32s3")]
        fn ram_pll_vol_cal();
    }
    unsafe {
        #[cfg(feature = "esp32c3")]
        let cases = [
            (2412u32, 1u32, 0u32, [91, 177, 59]),
            (2437u32, 2u32, 100u32, [69, 139, 187]),
            (2484u32, 3u32, 0u32, [37, 0, 0]),
            (2400u32, 0u32, 0u32, [48, 0, 0]),
            (0u32, 1u32, 0u32, [224, 24, 55]),
            (2412u32, 257u32, 65535u32, [95, 13, 150]),
            (65535u32, 3u32, 32768u32, [253, 183, 49]),
            (4294967295u32, 255u32, 4294967295u32, [224, 150, 56]),
        ];
        #[cfg(feature = "esp32s3")]
        let cases = [
            (2412u32, 1u32, 0u32, [91, 177, 59]),
            (2437u32, 2u32, 100u32, [69, 139, 187]),
            (2484u32, 3u32, 0u32, [50, 204, 204]),
            (2400u32, 0u32, 0u32, [48, 0, 0]),
            (0u32, 1u32, 0u32, [224, 24, 55]),
            (2412u32, 257u32, 65535u32, [91, 177, 55]),
            (65535u32, 3u32, 32768u32, [103, 66, 97]),
            (4294967295u32, 255u32, 4294967295u32, [224, 150, 56]),
        ];
        for (frequency, selector, offset, expected) in cases {
            let mut output = [0xa5u8; 5];
            rfpll_set_freq(frequency, selector, offset, output.as_mut_ptr().add(1));
            assert_eq!(output[0], 0xa5);
            assert_eq!(output[4], 0xa5);
            assert_eq!(&output[1..4], &expected);
        }
        let param = (&raw const phy_param).cast::<u8>();
        info!(
            "stage=phy_rfpll cycle={} checked={} channel={} selector={} offset={}",
            cycle,
            cases.len(),
            param.add(0x1f2).read_volatile(),
            param.add(0xf3).read_volatile(),
            param.add(0xe0).cast::<i16>().read_volatile()
        );
        #[cfg(feature = "esp32c3")]
        let entries = [
            (0, restart_cal as *const () as usize),
            (1, write_rfpll_sdm as *const () as usize),
            (2, wait_rfpll_cal_end as *const () as usize),
            (3, rfpll_set_freq as *const () as usize),
            (4, correct_rfpll_offset as *const () as usize),
            (5, rom2_write_pll_cap as *const () as usize),
            (6, rom2_read_pll_cap as *const () as usize),
            (7, ram2_rfpll_cap_correct as *const () as usize),
            (8, rfpll_cap_init_cal as *const () as usize),
            (9, set_rfpll_freq as *const () as usize),
            (10, set_rf_freq_offset as *const () as usize),
            (11, set_channel_rfpll_freq as *const () as usize),
            (12, chip_v7_set_chan_misc as *const () as usize),
            (13, chip_v7_set_chan as *const () as usize),
            (14, chip_v7_set_chan_offset as *const () as usize),
            (15, chip_v7_set_chan_ana as *const () as usize),
        ];
        #[cfg(feature = "esp32s3")]
        let entries = [
            (0, restart_cal as *const () as usize),
            (1, write_rfpll_sdm as *const () as usize),
            (2, wait_rfpll_cal_end as *const () as usize),
            (3, rfpll_set_freq as *const () as usize),
            (4, correct_rfpll_offset as *const () as usize),
            (5, ram_write_pll_cap as *const () as usize),
            (6, read_pll_cap as *const () as usize),
            (7, rfpll_cap_correct as *const () as usize),
            (8, rfpll_cap_init_cal as *const () as usize),
            (9, set_rfpll_freq as *const () as usize),
            (10, set_rf_freq_offset as *const () as usize),
            (11, set_channel_rfpll_freq as *const () as usize),
            (12, chip_v7_set_chan_misc as *const () as usize),
            (13, chip_v7_set_chan as *const () as usize),
            (14, chip_v7_set_chan_offset as *const () as usize),
            (15, chip_v7_set_chan_ana as *const () as usize),
            (16, phy_set_freq as *const () as usize),
            (17, ram_pll_vol_cal as *const () as usize),
        ];
        for (operation, address) in entries {
            info!(
                "stage=phy_rfpll_entry cycle={} operation={} address={:#x}",
                cycle, operation, address
            );
        }
        #[cfg(feature = "esp32c3")]
        let slots = [40, 428, 436, 440, 444, 504, 388, 392, 8, 12, 120, 96];
        #[cfg(feature = "esp32s3")]
        let slots = [
            40, 392, 400, 404, 408, 524, 468, 352, 356, 8, 12, 108, 588, 612,
        ];
        for slot in slots {
            let table = (&raw const g_phyFuns).read_volatile();
            let target = table.add(slot).cast::<usize>().read_volatile();
            assert_ne!(target, 0);
            info!(
                "stage=phy_rfpll_slot cycle={} slot={:#x} target={:#x}",
                cycle, slot, target
            );
        }
    }
}

/// Observe hardware-frequency entry placement and state after normal PHY init.
/// This probe neither starts a busy wait nor programs frequency memory.
unsafe fn inspect_hw_freq(cycle: u32) {
    unsafe extern "C" {
        static mut phy_param: u8;
        static mut g_phyFuns: *const u8;
        fn wait_freq_set_busy();
        #[cfg_attr(feature = "esp32c3", link_name = "ram1_phy_dis_hw_set_freq")]
        #[cfg_attr(feature = "esp32s3", link_name = "ram_phy_dis_hw_set_freq")]
        fn disable();
        #[cfg_attr(feature = "esp32c3", link_name = "rom1_phy_en_hw_set_freq")]
        #[cfg_attr(feature = "esp32s3", link_name = "ram_phy_en_hw_set_freq")]
        fn enable();
        fn wr_rf_freq_mem();
        fn freq_i2c_write_set();
        #[cfg_attr(feature = "esp32c3", link_name = "rom2_pll_cap_mem_update")]
        #[cfg_attr(feature = "esp32s3", link_name = "pll_cap_mem_update")]
        fn cap_memory();
        fn get_rf_freq_init();
        fn freq_get_i2c_data();
        fn freq_i2c_data_write();
        fn set_chan_freq_hw_init();
        fn set_chan_freq_sw_start();
    }
    unsafe {
        let param = &raw const phy_param;
        let flags = param.add(0x120).cast::<u32>().read_volatile();
        let bias = param.add(0xde).cast::<u16>().read_volatile();
        let offset = param.add(0xe2).cast::<i16>().read_volatile();
        let saved = param
            .add(if cfg!(feature = "esp32s3") {
                0x2aa
            } else {
                0x326
            })
            .cast::<u16>()
            .read_volatile();
        info!(
            "stage=phy_hw_freq cycle={} flags={:#x} bias={} offset={} saved={} passive=true",
            cycle, flags, bias, offset, saved
        );
        let entries = [
            wait_freq_set_busy as *const () as usize,
            disable as *const () as usize,
            enable as *const () as usize,
            wr_rf_freq_mem as *const () as usize,
            freq_i2c_write_set as *const () as usize,
            cap_memory as *const () as usize,
            get_rf_freq_init as *const () as usize,
            freq_get_i2c_data as *const () as usize,
            freq_i2c_data_write as *const () as usize,
            set_chan_freq_hw_init as *const () as usize,
            set_chan_freq_sw_start as *const () as usize,
        ];
        for (operation, address) in entries.into_iter().enumerate() {
            if operation < 3 {
                assert!((0x40300000..0x40400000).contains(&address));
            }
            info!(
                "stage=phy_hw_freq_entry cycle={} operation={} address={:#x}",
                cycle, operation, address
            );
        }
        #[cfg(feature = "esp32c3")]
        let slots = [0x28, 0x114, 0x1ac, 0x1b8, 0x1bc];
        #[cfg(feature = "esp32s3")]
        let slots = [0x28, 0x100, 0x188, 0x194, 0x198, 0x20c];
        for slot in slots {
            let table = (&raw const g_phyFuns).read_volatile();
            let target = table.add(slot).cast::<usize>().read_volatile();
            assert_ne!(target, 0);
            info!(
                "stage=phy_hw_freq_slot cycle={} slot={:#x} target={:#x}",
                cycle, slot, target
            );
        }
    }
}

/// Observe register-member entries and immutable parameter snapshots after init.
/// Does not call tone, IQ, AGC, RF switching or any register-programming helper.
unsafe fn inspect_registers(cycle: u32) {
    unsafe extern "C" {
        static mut phy_param: u8;
        static mut g_phyFuns: *const u8;
        #[cfg_attr(feature = "esp32c3", link_name = "ram1_set_pbus_reg")]
        #[cfg_attr(feature = "esp32s3", link_name = "ram_set_pbus_reg")]
        fn entry_0();
        #[cfg_attr(feature = "esp32c3", link_name = "rom1_tx_paon_set")]
        #[cfg_attr(feature = "esp32s3", link_name = "ram_wifi_tx_dig_gain_reg")]
        fn entry_1();
        #[link_name = "btbb_wifi_bb_cfg2"]
        fn entry_2();
        #[link_name = "rx_agc_reg_opt"]
        fn entry_3();
        #[link_name = "rx_11b_opt"]
        fn entry_4();
        #[cfg_attr(feature = "esp32c3", link_name = "rom1_disable_wifi_agc")]
        #[cfg_attr(feature = "esp32s3", link_name = "ram_disable_wifi_agc")]
        fn entry_5();
        #[cfg_attr(feature = "esp32c3", link_name = "rom1_enable_wifi_agc")]
        #[cfg_attr(feature = "esp32s3", link_name = "ram_enable_wifi_agc")]
        fn entry_6();
        #[cfg_attr(feature = "esp32c3", link_name = "ram1_fe_i2c_reg_renew")]
        #[cfg_attr(feature = "esp32s3", link_name = "ram_fe_i2c_reg_renew")]
        fn entry_7();
        #[link_name = "phy_wifi_enable_set"]
        fn entry_8();
        #[link_name = "txiq_set_reg"]
        fn entry_9();
        #[link_name = "rxiq_set_reg"]
        fn entry_10();
        #[link_name = "start_tx_tone_step"]
        fn entry_11();
        #[link_name = "stop_tx_tone"]
        fn entry_12();
        #[cfg_attr(feature = "esp32c3", link_name = "rom1_set_noise_floor")]
        #[cfg_attr(feature = "esp32s3", link_name = "ram_set_noise_floor")]
        fn entry_13();
        #[link_name = "phy_freq_correct"]
        fn entry_14();
        #[link_name = "force_txrx_off"]
        fn entry_15();
    }
    unsafe {
        let entries = [
            entry_0 as *const () as usize,
            entry_1 as *const () as usize,
            entry_2 as *const () as usize,
            entry_3 as *const () as usize,
            entry_4 as *const () as usize,
            entry_5 as *const () as usize,
            entry_6 as *const () as usize,
            entry_7 as *const () as usize,
            entry_8 as *const () as usize,
            entry_9 as *const () as usize,
            entry_10 as *const () as usize,
            entry_11 as *const () as usize,
            entry_12 as *const () as usize,
            entry_13 as *const () as usize,
            entry_14 as *const () as usize,
            entry_15 as *const () as usize,
        ];
        for (operation, address) in entries.into_iter().enumerate() {
            if operation < 9 {
                assert!((0x40300000..0x40400000).contains(&address));
            }
            info!(
                "stage=phy_reg_entry cycle={} operation={} address={:#x}",
                cycle, operation, address
            );
        }
        let p = (&raw const phy_param).add(if cfg!(feature = "esp32s3") {
            0x2ac
        } else {
            0x328
        });
        for index in 0..6 {
            let value = p.add(index * 4).cast::<u32>().read_volatile();
            info!(
                "stage=phy_reg_param cycle={} index={} value={:#x} passive=true",
                cycle, index, value
            );
        }
        let slot = if cfg!(feature = "esp32s3") {
            0x190
        } else {
            0x1b4
        };
        let table = (&raw const g_phyFuns).read_volatile();
        let target = table.add(slot).cast::<usize>().read_volatile();
        assert_ne!(target, 0);
        info!(
            "stage=phy_reg_slot cycle={} slot={:#x} target={:#x}",
            cycle, slot, target
        );
    }
}

/// Observe receive-gain entries and post-init counts without starting calibration.
unsafe fn inspect_rx_gain(cycle: u32) {
    unsafe extern "C" {
        static mut phy_param: u8;
        fn gen_rx_gain_table();
        fn wr_rx_gain_mem();
        fn set_rx_gain_param();
        fn set_rx_gain_table();
        fn phy_rx_table_init();
    }
    unsafe {
        let entries = [
            gen_rx_gain_table as *const () as usize,
            wr_rx_gain_mem as *const () as usize,
            set_rx_gain_param as *const () as usize,
            set_rx_gain_table as *const () as usize,
            phy_rx_table_init as *const () as usize,
        ];
        for (operation, address) in entries.into_iter().enumerate() {
            info!(
                "stage=phy_rx_gain_entry cycle={} operation={} address={:#x}",
                cycle, operation, address
            );
        }
        let p = &raw const phy_param;
        let first = p.add(0x1f5).read_volatile();
        let second = p.add(0x1f6).read_volatile();
        info!(
            "stage=phy_rx_gain_counts cycle={} first={} second={} passive=true",
            cycle, first, second
        );
    }
}

/// Observe gain bindings and table fingerprints without starting calibration.
unsafe fn inspect_tx_gain(cycle: u32) {
    #[cfg(feature = "esp32c3")]
    unsafe {
        unsafe extern "C" {
            static mut phy_param: u8;
            static mut g_phyFuns: *const u8;
            fn rom1_wifi_tx_dig_gain();
            fn bt_chan_pwr_interp();
            fn rom1_get_rate_fcc_index();
            fn rom1_get_chan_target_power();
            fn rom2_get_tx_gain_value1();
            fn rom1_bt_get_tx_gain_new();
            fn rom1_wifi_get_tx_gain();
            fn ram1_wifi_set_tx_gain();
            fn rom1_bt_set_tx_gain();
            fn bt_tx_gain_init();
            fn txcal_gain_check();
        }
        let entries = [
            rom1_wifi_tx_dig_gain as *const () as usize,
            bt_chan_pwr_interp as *const () as usize,
            rom1_get_rate_fcc_index as *const () as usize,
            rom1_get_chan_target_power as *const () as usize,
            rom2_get_tx_gain_value1 as *const () as usize,
            rom1_bt_get_tx_gain_new as *const () as usize,
            rom1_wifi_get_tx_gain as *const () as usize,
            ram1_wifi_set_tx_gain as *const () as usize,
            rom1_bt_set_tx_gain as *const () as usize,
            bt_tx_gain_init as *const () as usize,
            txcal_gain_check as *const () as usize,
        ];
        for (operation, address) in entries.into_iter().enumerate() {
            info!(
                "stage=phy_tx_gain_entry cycle={} operation={} address={:#x}",
                cycle, operation, address
            );
        }
        let table = (&raw const g_phyFuns).read_volatile();
        for slot in [296, 648, 588, 572, 584] {
            let target = table.add(slot).cast::<usize>().read_volatile();
            assert_ne!(target, 0);
            info!(
                "stage=phy_tx_gain_slot cycle={} slot={:#x} target={:#x}",
                cycle, slot, target
            );
        }
        let param = &raw const phy_param;
        for (table, offset, count) in [(0, 14, 90), (1, 0x68, 42)] {
            let mut fingerprint = 0x811c9dc5u32;
            for index in 0..count {
                fingerprint = (fingerprint ^ param.add(offset + index).read_volatile() as u32)
                    .wrapping_mul(0x01000193);
            }
            info!(
                "stage=phy_tx_gain_table cycle={} table={} fingerprint={:#x} passive=true",
                cycle, table, fingerprint
            );
        }
    }
    #[cfg(feature = "esp32s3")]
    unsafe {
        unsafe extern "C" {
            static mut phy_param: u8;
            static mut g_phyFuns: *const u8;
            fn ram_wifi_tx_dig_gain();
            fn bt_chan_pwr_interp();
            fn ram_get_rate_fcc_index();
            fn ram_get_chan_target_power();
            fn get_tx_gain_value();
            fn ram_bt_get_tx_gain();
            fn ram_wifi_get_tx_gain();
            fn ram_wifi_set_tx_gain();
            fn ram_bt_set_tx_gain();
            fn bt_tx_gain_init();
            fn tx_gain_set();
            fn dig_gain_check();
        }
        let entries = [
            ram_wifi_tx_dig_gain as *const () as usize,
            bt_chan_pwr_interp as *const () as usize,
            ram_get_rate_fcc_index as *const () as usize,
            ram_get_chan_target_power as *const () as usize,
            get_tx_gain_value as *const () as usize,
            ram_bt_get_tx_gain as *const () as usize,
            ram_wifi_get_tx_gain as *const () as usize,
            ram_wifi_set_tx_gain as *const () as usize,
            ram_bt_set_tx_gain as *const () as usize,
            bt_tx_gain_init as *const () as usize,
            tx_gain_set as *const () as usize,
            dig_gain_check as *const () as usize,
        ];
        for (operation, address) in entries.into_iter().enumerate() {
            info!(
                "stage=phy_tx_gain_entry cycle={} operation={} address={:#x}",
                cycle, operation, address
            );
        }
        let table = (&raw const g_phyFuns).read_volatile();
        for slot in [612, 552, 536, 548, 624, 252] {
            let target = table.add(slot).cast::<usize>().read_volatile();
            assert_ne!(target, 0);
            info!(
                "stage=phy_tx_gain_slot cycle={} slot={:#x} target={:#x}",
                cycle, slot, target
            );
        }
        let param = &raw const phy_param;
        for (table, offset, count) in [(0, 14, 90), (1, 0x68, 42)] {
            let mut fingerprint = 0x811c9dc5u32;
            for index in 0..count {
                fingerprint = (fingerprint ^ param.add(offset + index).read_volatile() as u32)
                    .wrapping_mul(0x01000193);
            }
            info!(
                "stage=phy_tx_gain_table cycle={} table={} fingerprint={:#x} passive=true",
                cycle, table, fingerprint
            );
        }
    }
}

/// Observe initialization bindings and configuration after the PHY owns state.
/// Reading these bytes does not invoke initialization or calibration a second time.
unsafe fn inspect_init(cycle: u32) {
    #[cfg(feature = "esp32c3")]
    unsafe {
        unsafe extern "C" {
            static mut phy_param: u8;
            static mut chip7_phy_init_ctrl: u8;
            static mut g_phyFuns: *const u8;
            fn phy_get_romfunc_addr();
            fn rf_init();
            fn register_chipv7_phy_init_param();
            fn phy_set_mac_data();
            fn phy_rfcal_data_sub();
            fn rf_cal_data_recovery();
            fn phy_rfcal_data_check_value();
            fn rf_cal_data_backup();
            fn phy_rfcal_data_check();
            fn rf_cal_level_check();
            fn bb_init();
            fn register_chipv7_phy();
            fn get_txcap_data();
            fn ram1_phy_wakeup_init();
            fn ram1_phy_close_rf();
        }
        let entries = [
            (0u32, phy_get_romfunc_addr as *const () as usize),
            (1u32, rf_init as *const () as usize),
            (2u32, register_chipv7_phy_init_param as *const () as usize),
            (3u32, phy_set_mac_data as *const () as usize),
            (4u32, phy_rfcal_data_sub as *const () as usize),
            (5u32, rf_cal_data_recovery as *const () as usize),
            (6u32, phy_rfcal_data_check_value as *const () as usize),
            (7u32, rf_cal_data_backup as *const () as usize),
            (8u32, phy_rfcal_data_check as *const () as usize),
            (9u32, rf_cal_level_check as *const () as usize),
            (10u32, bb_init as *const () as usize),
            (11u32, register_chipv7_phy as *const () as usize),
            (12u32, get_txcap_data as *const () as usize),
            (16u32, ram1_phy_wakeup_init as *const () as usize),
            (17u32, ram1_phy_close_rf as *const () as usize),
        ];
        for (operation, address) in entries {
            info!(
                "stage=phy_init_entry cycle={} operation={} address={:#x}",
                cycle, operation, address
            );
        }
        let param = &raw const phy_param;
        let control = &raw const chip7_phy_init_ctrl;
        let table = (&raw const g_phyFuns).read_volatile();
        let initialized = param.add(229).read_volatile();
        assert_eq!(initialized, 1, "PHY initialization flag was not recorded");
        assert!(!table.is_null());
        info!(
            "stage=phy_init_state cycle={} param={:#x} size=848 control={:#x} table_global={:#x} table={:#x} initialized={}",
            cycle,
            param as usize,
            control as usize,
            (&raw const g_phyFuns) as usize,
            table as usize,
            initialized
        );
        for (region, base, count) in [(0, param.add(242), 46), (1, control, 42)] {
            let mut fingerprint = 0x811c9dc5u32;
            for i in 0..count {
                fingerprint =
                    (fingerprint ^ base.add(i).read_volatile() as u32).wrapping_mul(0x01000193);
            }
            info!(
                "stage=phy_init_config cycle={} region={} fingerprint={:#x} passive=true",
                cycle, region, fingerprint
            );
        }
    }
    #[cfg(feature = "esp32s3")]
    unsafe {
        unsafe extern "C" {
            static mut phy_param: u8;
            static mut chip7_phy_init_ctrl: u8;
            static mut g_phyFuns: *const u8;
            fn phy_get_romfunc_addr();
            fn rf_init();
            fn register_chipv7_phy_init_param();
            fn phy_set_mac_data();
            fn phy_rfcal_data_sub();
            fn rf_cal_data_recovery();
            fn phy_rfcal_data_check_value();
            fn rf_cal_data_backup();
            fn phy_rfcal_data_check();
            fn bb_init();
            fn register_chipv7_phy();
            fn pwr_limit_force();
            fn esp_phy_efuse_get_chip_ver_pkg();
            fn get_chip_version();
            fn ram_phy_wakeup_init();
            fn ram_phy_close_rf();
        }
        let entries = [
            (0u32, phy_get_romfunc_addr as *const () as usize),
            (1u32, rf_init as *const () as usize),
            (2u32, register_chipv7_phy_init_param as *const () as usize),
            (3u32, phy_set_mac_data as *const () as usize),
            (4u32, phy_rfcal_data_sub as *const () as usize),
            (5u32, rf_cal_data_recovery as *const () as usize),
            (6u32, phy_rfcal_data_check_value as *const () as usize),
            (7u32, rf_cal_data_backup as *const () as usize),
            (8u32, phy_rfcal_data_check as *const () as usize),
            (10u32, bb_init as *const () as usize),
            (11u32, register_chipv7_phy as *const () as usize),
            (13u32, pwr_limit_force as *const () as usize),
            (14u32, esp_phy_efuse_get_chip_ver_pkg as *const () as usize),
            (15u32, get_chip_version as *const () as usize),
            (16u32, ram_phy_wakeup_init as *const () as usize),
            (17u32, ram_phy_close_rf as *const () as usize),
        ];
        for (operation, address) in entries {
            info!(
                "stage=phy_init_entry cycle={} operation={} address={:#x}",
                cycle, operation, address
            );
        }
        let param = &raw const phy_param;
        let control = &raw const chip7_phy_init_ctrl;
        let table = (&raw const g_phyFuns).read_volatile();
        let initialized = param.add(229).read_volatile();
        assert_eq!(initialized, 1, "PHY initialization flag was not recorded");
        assert!(!table.is_null());
        info!(
            "stage=phy_init_state cycle={} param={:#x} size=740 control={:#x} table_global={:#x} table={:#x} initialized={}",
            cycle,
            param as usize,
            control as usize,
            (&raw const g_phyFuns) as usize,
            table as usize,
            initialized
        );
        for (region, base, count) in [(0, param.add(242), 46), (1, control, 42)] {
            let mut fingerprint = 0x811c9dc5u32;
            for i in 0..count {
                fingerprint =
                    (fingerprint ^ base.add(i).read_volatile() as u32).wrapping_mul(0x01000193);
            }
            info!(
                "stage=phy_init_config cycle={} region={} fingerprint={:#x} passive=true",
                cycle, region, fingerprint
            );
        }
    }
}

/// Exercise full PHY guard teardown/wakeup before creating the MAC driver.
/// Station reconnects alone keep a PHY guard alive and do not cover this path.
#[esp_rtos::main]
async fn main(_spawner: Spawner) {
    let peripherals = common_init();
    embassy_init(peripherals.TIMG0, peripherals.SW_INTERRUPT);
    info!("stage=boot test=phy_lifetime_smoke");
    assert!(esp_phy::last_calibration_result().is_none());

    // Match LowLevelDriver::init's pre-PHY power/isolation/clock sequence.
    // There is no MAC driver, DMA or radio task yet; enable_phy() alone only
    // supplies the common PHY clocks and does not prepare the Wi-Fi domain.
    esp_hal::peripherals::LPWR::regs()
        .dig_pwc()
        .modify(|_, w| w.wifi_force_pd().clear_bit());
    esp_hal::peripherals::LPWR::regs()
        .dig_iso()
        .modify(|_, w| w.wifi_force_iso().clear_bit());
    esp_hal::peripherals::APB_CTRL::regs()
        .wifi_clk_en()
        .modify(|r, w| unsafe { w.bits(r.bits() | 0x00fb9fcf) });

    for cycle in 1..=3 {
        let guard = esp_phy::enable_phy();
        // This describes the INPUT calibration data. The fresh zero-filled
        // buffer can report DataCheckFailed even after FULL calibration has
        // generated valid output (see PHY-SOURCE-VALIDATION.md). Later cycles
        // report the cached status while exercising wakeup/restore.
        let status =
            esp_phy::last_calibration_result().expect("PHY did not record calibration completion");
        info!(
            "stage=phy_calibration cycle={} input_status={:?}",
            cycle, status
        );
        let mut calibration = [0; esp_phy::PHY_CALIBRATION_DATA_LENGTH];
        esp_phy::backup_phy_calibration_data(&mut calibration)
            .expect("No output calibration data after initialization");
        assert!(
            calibration.iter().any(|&byte| byte != 0),
            "Empty calibration output"
        );
        info!("stage=phy_enabled cycle={}", cycle);
        unsafe {
            inspect_sensor_lifecycle(cycle);
            inspect_temperature(cycle);
            inspect_pbus(cycle);
            inspect_i2c(cycle);
            inspect_api(cycle);
            inspect_basic(cycle);
            inspect_feature(cycle);
            inspect_debug(cycle);
            inspect_pwdet(cycle);
            inspect_analog(cycle);
            inspect_track(cycle);
            inspect_rfpll(cycle);
            inspect_hw_freq(cycle);
            inspect_registers(cycle);
            inspect_rx_gain(cycle);
            inspect_tx_gain(cycle);
            inspect_init(cycle);
        }
        Timer::after_millis(100).await;
        // No MAC driver or other PHY guard exists: releasing this last guard
        // invokes the adapter's register backup, RF shutdown and clock release.
        drop(guard);
        #[cfg(feature = "esp32c3")]
        unsafe {
            unsafe extern "C" {
                static mut phy_param: [u8; 848];
            }
            let closed = (&raw const phy_param)
                .cast::<u8>()
                .add(0x320)
                .read_volatile();
            assert_eq!(closed, 1, "API RF-close state was not recorded");
            info!("stage=phy_api_closed cycle={} flag={}", cycle, closed);
        }
        let off_flag = unsafe { sensor_off_flag() };
        assert_eq!(off_flag, 1, "Sensor shutdown state was not recorded");
        info!(
            "stage=phy_sensor_released cycle={} off_flag={}",
            cycle, off_flag
        );
        info!("stage=phy_released cycle={}", cycle);
        Timer::after_millis(100).await;
    }

    // Initialization now takes the calibrated wakeup path. Check that receive
    // works afterward, rather than treating surviving a guard drop as enough.
    let mut wifi = wifi_init(peripherals.WIFI);
    wifi.set_scanning_mode(0, ScanningMode::BeaconsOnly)
        .unwrap();
    let mut received = 0;
    for channel in 1..=11 {
        wifi.set_channel(channel).unwrap();
        if let Ok(frame) = with_timeout(Duration::from_millis(300), wifi.receive()).await {
            let mpdu = frame.mpdu_buffer();
            if mpdu.len() >= 24 && mpdu[0] & 0xfc == 0x80 {
                received += 1;
            }
        }
    }
    assert!(received > 0, "No receive after PHY wakeup");
    info!(
        "stage=complete test=phy_lifetime_smoke received={}",
        received
    );
}
