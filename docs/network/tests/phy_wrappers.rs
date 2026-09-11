//! Exercise production modules against external RAM-call and PHY-data boundaries.
//! The independent original-instruction oracle lives in phy-wrapper-oracle/.

#[path = "../../../esp-wifi-hal/src/phy_wrappers.rs"]
mod phy_wrappers;
#[path = "../../../vendor/esp-phy/src/usb_phy.rs"]
mod usb_phy;

use std::{cell::RefCell, sync::Mutex};

thread_local! {
    static CALLS: RefCell<Vec<(u8, u8)>> = const { RefCell::new(Vec::new()) };
}

#[unsafe(no_mangle)]
extern "C" fn ram_tx_pwctrl_background(enabled: u8, mode: u8) {
    CALLS.with(|calls| calls.borrow_mut().push((enabled, mode)));
}

#[cfg(esp32c3)]
const PARAM_SIZE: usize = 848;
#[cfg(esp32s3)]
const PARAM_SIZE: usize = 740;

// The source under test names the actual external data object. Keeping that
// symbol in the harness exercises its pointer arithmetic and store operation.
#[unsafe(no_mangle)]
static mut phy_param: [u8; PARAM_SIZE] = [0; PARAM_SIZE];
static PARAM_LOCK: Mutex<()> = Mutex::new(());

#[test]
fn every_valid_c_byte_pair_reaches_the_retained_ram_callee_once_in_order() {
    for enabled in 0..=u8::MAX {
        CALLS.with(|calls| calls.borrow_mut().clear());
        for mode in 0..=u8::MAX {
            unsafe { phy_wrappers::tx_pwctrl_background(enabled, mode) };
        }
        CALLS.with(|calls| {
            let calls = calls.borrow();
            assert_eq!(calls.len(), 256);
            for (mode, &(actual_enabled, actual_mode)) in calls.iter().enumerate() {
                assert_eq!((actual_enabled, actual_mode), (enabled, mode as u8));
            }
        });
    }
}

#[test]
fn usb_store_matches_the_original_instruction_offset_and_preserves_every_other_byte() {
    let _guard = PARAM_LOCK.lock().unwrap();
    // Independently transcribed from original SB relocation / ADDMI+S8I.
    #[cfg(esp32c3)]
    let original_store_offset = 0x323;
    #[cfg(esp32s3)]
    let original_store_offset = 0x200 + 166;

    for seed in 0..=u8::MAX {
        for enabled in [false, true] {
            let mut expected = [0; PARAM_SIZE];
            for (index, byte) in expected.iter_mut().enumerate() {
                *byte = seed.wrapping_add(index as u8);
            }
            unsafe {
                (&raw mut phy_param).write(expected);
                usb_phy::phy_bbpll_en_usb(enabled);
            }
            expected[original_store_offset] = u8::from(enabled);
            let actual = unsafe { (&raw const phy_param).read() };
            assert_eq!(actual, expected, "seed={seed} enabled={enabled}");
        }
    }
}

#[test]
fn usb_enable_then_disable_uses_the_same_byte_without_affecting_other_phy_state() {
    let _guard = PARAM_LOCK.lock().unwrap();
    #[cfg(esp32c3)]
    let original_store_offset = 0x323;
    #[cfg(esp32s3)]
    let original_store_offset = 0x2a6;
    unsafe { (&raw mut phy_param).write([0xa5; PARAM_SIZE]) };
    for enabled in [true, true, false, false, true, false] {
        unsafe { usb_phy::phy_bbpll_en_usb(enabled) };
        let actual = unsafe { (&raw const phy_param).read() };
        let mut expected = [0xa5; PARAM_SIZE];
        expected[original_store_offset] = u8::from(enabled);
        assert_eq!(actual, expected);
    }
}
