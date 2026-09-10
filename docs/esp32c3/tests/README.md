# C3 MAC initialization transaction tests

The checked-in traces cover the complete Rust C3 MAC initialization
and eight additional MAC helper bodies. They were derived by bounded
interpretation of actual RV32IMC instructions from two separately linked vendor
baselines: ESP-IDF 5.4 and esp-wifi-sys-esp32c3 0.2.0. The archives differ
bytewise, but all 260 exercised instruction traces agree. The Rust implementation
produced the same ordered 32-bit MMIO transactions and the modeled PHY/clock
callback events.

Run from the repository root:

```sh
sh docs/esp32c3/tests/run-tests.sh
```

The test uses stable Rust and the checked-in trace data. Neither the private
reconstruction framework nor a model, cross compiler, SDK or board is required.

There are 260 cases. Four initial register patterns each exercise full
initialization, four fixed helpers, three priority helpers with eight input
values, and the RTC helper with six enable values and six calibration values.
The test compares every read and write in order, including antenna's two passes
and separate read/modify/write operations. It checks C3's RX descriptor range
values and its full-register RTC enable branch, including enable=256.

The oracle is a small instruction interpreter with explicit external-call
stubs, not a CPU, DMA engine or radio emulator. Unknown instructions fail. MMIO
is modeled as ordinary 32-bit registers; ready status is preset, the initial RX
descriptor base is zero, the clock callback returns a fixed value and Bluetooth
coexistence remains disabled. These traces do not validate interrupt timing,
hardware side effects, PHY behavior, MMIO bus ordering, Bluetooth scheduling,
power transitions or device reliability. The original initialization does not
contain explicit RISC-V FENCE instructions; this test does not establish whether
additional synchronization is needed outside the observed path.

`trace-evidence.json` records the baseline ELF and archive/member hashes,
function addresses, audited Rust source hash, oracle hash and trace file hash.
The addresses identify those analysis inputs, not fixed ROM entry points.

To regenerate independently, obtain matching vendor inputs, extract the named
functions with GNU RISC-V objdump, and interpret or instrument their integer
instructions with the documented register seeds and external-call assumptions.
Preserve the exact access widths and transaction order; do not regenerate
expected traces by running the Rust implementation being tested. Compare the
two original baselines before accepting new expected data. Full baseline
firmware, credentials and private harness code are not included here.
