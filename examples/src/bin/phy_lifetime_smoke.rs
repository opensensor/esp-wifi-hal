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
            inspect_temperature(cycle);
        }
        Timer::after_millis(100).await;
        // No MAC driver or other PHY guard exists: releasing this last guard
        // invokes the adapter's register backup, RF shutdown and clock release.
        drop(guard);
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
