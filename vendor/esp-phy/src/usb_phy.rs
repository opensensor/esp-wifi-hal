//! C3/S3 byte-store wrapper reviewed against esp-wifi-sys 0.2.0 libphy.
//! The rest of PHY initialization and the parameter object remain vendor code.

#[cfg(esp32c3)]
const USB_ENABLE_OFFSET: usize = 0x323;
#[cfg(esp32s3)]
const USB_ENABLE_OFFSET: usize = 0x2a6;

// These are the complete data-symbol sizes in the pinned chip archives, not a
// description of the undocumented structure or a promise about future blobs.
#[cfg(esp32c3)]
const PHY_PARAM_SIZE: usize = 848;
#[cfg(esp32s3)]
const PHY_PARAM_SIZE: usize = 740;

const _: () = assert!(USB_ENABLE_OFFSET < PHY_PARAM_SIZE);

unsafe extern "C" {
    static mut phy_param: [u8; PHY_PARAM_SIZE];
}

/// Requires the PHY controller lock held by `PhyState::calibrate`.
#[inline(always)]
pub(super) unsafe fn phy_bbpll_en_usb(enabled: bool) {
    // Preserve one byte store before register_chipv7_phy; do not create a
    // Rust reference to this externally shared vendor parameter object.
    unsafe {
        (&raw mut phy_param)
            .cast::<u8>()
            .add(USB_ENABLE_OFFSET)
            .write_volatile(u8::from(enabled));
    }
}
