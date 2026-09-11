# Published esp-phy 0.2.0 source

This directory vendors the published `esp-phy` 0.2.0 package, whose Cargo VCS
metadata identifies upstream `esp-rs/esp-hal` commit
`347003de8a48320bb7724f53045be3afa9204411`, subdirectory `esp-phy`.
The published crate archive SHA-256 is
`e7c0a29815cd105ae1a02f3d0c6e7aafda9504a41effae17fac4c3f827719228`;
every original copied file was checked against that archive rather than
trusting a possibly modified local registry cache.
`UPSTREAM-SHA256.json` records the original contents of every copied package
file before modification. MIT and Apache licenses come from that exact
upstream commit. Registry bookkeeping, the published lockfile, the redundant
original manifest and an empty `esp-phy` file are omitted.

The normalized registry manifest is retained so sibling workspace crates stay
on their published versions. Its two C3/S3 `esp-wifi-sys` requirements are
tightened to `=0.2.0` to pin the private data layout. The only source changes are the C3/S3 USB-enable
wrapper in `src/usb_phy.rs` and its call site in `src/lib.rs`. Other chips keep
their original FFI call. Configuration, PHY lifetime management, calibration
selection and the call ordering are unchanged.

The replacement depends on the exact C3/S3 `esp-wifi-sys` 0.2.0 `phy_param`
layout. It writes one byte before the existing `register_chipv7_phy` call;
it does not implement PLL calibration. See
[`docs/network/PHY-WRAPPERS.md`](../../docs/network/PHY-WRAPPERS.md) for evidence
and validation. Keep this small delta explicit when updating the vendor copy.
