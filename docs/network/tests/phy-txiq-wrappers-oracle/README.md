# TX IQ initialization wrappers

`txiq_cal_init` and `bt_txiq_cal` are compared with pinned original C3/S3
instructions. The corpus has 2,048 cases per chip, covering every attenuation
byte, both flag gates, and callbacks that change flags, attenuation, the live
table pointer, and callback slots. Callback reads return full words.

Run `sh docs/network/tests/run-phy-txiq-wrappers.sh` from the repository root.
The model and actual Rust implementation at optimization levels 0 and 2 must
match ordered reads, writes, helper arguments, and final parameter/analog state.
All original PCs and conditional edges must be covered; no coverage exemptions.
Checks also run with Python assertions disabled.

The native adapter retains volatile state/table access. C3 adds 20 to the
Bluetooth byte before signed narrowing; S3 does not. C3 reloads the table before
writing the final flags, whereas S3 writes flags first. Saved analog words are
restored without narrowing. The initialization wrapper retains its initial
attenuation across both helper calls and updates flags from a fresh read.

The output-only scratch is four aligned halfwords. Mode 2 of `rfcal_txiq` passes
it to `txdc_cal_v70`, whose two outer passes each store halfwords at offsets 0
and 2 before advancing by 4. The oracle writes all eight bytes and rejects
unaligned or out-of-frame output pointers. Helper arithmetic, analog calibration
quality, ROM implementations, and Bluetooth radio operation are outside this
wrapper comparison. Device Wi-Fi trials do not establish Bluetooth RF behavior.

`extract.py` follows reachable instructions rather than treating padding as
code. Baseline metadata pins original ELF/map hashes; instruction bytes and
body hashes are checked before execution. The final emitted firmware bodies
are compared separately before device trials.
