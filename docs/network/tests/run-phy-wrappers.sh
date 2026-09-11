#!/bin/sh
# Original-instruction and actual-source boundary tests; no firmware or device.
set -eu
test_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
test_out=$(mktemp -d)
trap 'rm -rf "$test_out"' EXIT HUP INT TERM
for chip in esp32c3 esp32s3; do
    for optimization in 0 2; do
        rustc +stable --edition 2024 --test --cfg "$chip" \
            -C "opt-level=$optimization" "$test_dir/phy_wrappers.rs" \
            -o "$test_out/$chip-$optimization"
        "$test_out/$chip-$optimization"
    done
done
