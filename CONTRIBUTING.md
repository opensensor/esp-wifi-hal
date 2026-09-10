# Contributing to OpenSensor esp-wifi-hal

Contributions belong at [opensensor/esp-wifi-hal](https://github.com/opensensor/esp-wifi-hal).
Open pull requests against `main` and report bugs in this repository's issue tracker.
OpenSensor Engineering maintains this fork independently of esp32-open-mac.

## AI-assisted contributions

**AI-assisted and AI-generated contributions are welcome.** Using an AI tool is
not, by itself, grounds for rejecting a contribution. We apply the same technical
review standards to all submissions, regardless of how they were produced.

The submitting contributor is responsible for the change: review the output,
explain its behavior and limitations, and help address review feedback. When AI
materially contributes code or reverse-engineering conclusions, briefly identify
the tool/model and describe the human review and validation performed. We do not
require private prompts, private tooling or a commercial model subscription.

Include the commands and evidence supporting correctness. State what you could
not test; contributions without access to a board are still welcome. A successful
compile, assembly similarity score or model assertion is not a device test.
Keep failed runs and known limitations visible when they affect the conclusion.

Preserve source attribution and compatible licensing. Submit only material you
have the right to contribute. Keep credentials, signing keys and private logs
out of submissions. Discuss code and evidence with specific, respectful feedback.

## Preparing a change

Explain the problem, the resulting behavior, and the scope of the change. Include
focused regression tests when fixing a behavioral bug. Documentation changes
do not need device tests. For register or DMA changes, cite the relevant register
evidence and describe the ordering, width, ownership or bounds affected.

Run the host checks with a C compiler, rustup and a stable Rust toolchain:

```sh
sh docs/esp32s3/tests/run-rust-tests.sh

# This separate smoltcp reproduction requires Rust >=1.91.
cargo +stable test --locked --target x86_64-unknown-linux-gnu \
  --manifest-path docs/esp32s3/tests/neighbor-repro/Cargo.toml
```

CI runs these commands on Linux. The smoltcp test confirms a known neighbor-cache
limitation; a passing result does not mean that limitation was fixed.

For embedded changes, build the affected chip features with the esp Xtensa
toolchain. If a change affects shared code, also check ESP32, S2 and S3. See
[the S3 guide](docs/esp32s3/RUST.md) for build and device-test commands. Record the
revision, board/chip, toolchain, test counts and any failures. Never describe an
untested device path as working.

Pull requests receive human review before acceptance. AI use neither guarantees
acceptance nor exempts a change from review. Retain the existing MIT OR Apache-2.0
licensing and copyright notices.
