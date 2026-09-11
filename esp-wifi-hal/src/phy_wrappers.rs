//! Source replacements for the small C3/S3 PHY forwarding wrappers.
//!
//! The calibration/tracking routine reached here is still supplied by libphy.
//! See `docs/network/PHY-WRAPPERS.md` for the original instruction contracts.

unsafe extern "C" {
    fn ram_tx_pwctrl_background(enabled: u8, mode: u8);
}

/// Forward exactly once, preserving the original wrapper's byte arguments.
///
/// Requires the same initialized, exclusive PHY access as the vendor routine.
#[inline(always)]
pub(crate) unsafe fn tx_pwctrl_background(enabled: u8, mode: u8) {
    // C3 tail-jumps directly. S3 narrows both registers to bytes before its
    // call8. Rust's u8 C ABI already supplies those byte-valued arguments.
    unsafe { ram_tx_pwctrl_background(enabled, mode) };
}
