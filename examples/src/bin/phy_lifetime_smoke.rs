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
        // After the first full calibration this reports its cached result;
        // later cycles exercise wakeup/restore without recalibrating.
        assert!(matches!(
            esp_phy::last_calibration_result(),
            Some(esp_phy::CalibrationResult::Ok)
        ));
        info!("stage=phy_enabled cycle={}", cycle);
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
