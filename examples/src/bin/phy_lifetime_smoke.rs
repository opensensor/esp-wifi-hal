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
        }
        Timer::after_millis(100).await;
        // No MAC driver or other PHY guard exists: releasing this last guard
        // invokes the adapter's register backup, RF shutdown and clock release.
        drop(guard);
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
