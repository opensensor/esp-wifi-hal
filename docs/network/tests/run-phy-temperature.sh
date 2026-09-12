#!/bin/sh
set -eu
test_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
test_out=$(mktemp -d)
trap 'rm -rf "$test_out"' EXIT HUP INT TERM
python3 -m unittest discover -s "$test_dir/phy-temperature-oracle" -q
python3 -O -m unittest discover -s "$test_dir/phy-temperature-oracle" -q
for chip in esp32c3 esp32s3; do
    python3 "$test_dir/phy-temperature-oracle/verify.py" "$chip" "$test_out/$chip.bin"
    for optimization in 0 2; do
        rustc +stable --edition 2024 --test --cfg "$chip" \
            -C "opt-level=$optimization" "$test_dir/phy_temperature.rs" \
            -o "$test_out/$chip-$optimization"
        PHY_TEMPERATURE_CASES="$test_out/$chip.bin" "$test_out/$chip-$optimization"
    done
done
