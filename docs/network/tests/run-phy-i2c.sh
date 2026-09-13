#!/bin/sh
set -eu
test_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
test_out=$(mktemp -d)
trap 'rm -rf "$test_out"' EXIT HUP INT TERM
python3 -m unittest discover -s "$test_dir/phy-i2c-oracle" -q
python3 -O -m unittest discover -s "$test_dir/phy-i2c-oracle" -q
for chip in esp32c3 esp32s3; do
    python3 "$test_dir/phy-i2c-oracle/verify.py" "$chip" "$test_out/$chip.bin"
    count=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]]["cases"])' \
        "$test_dir/phy-i2c-oracle/expected-results.json" "$chip")
    for optimization in 0 2; do
        rustc +stable --edition 2024 --test --cfg "$chip" \
            -C "opt-level=$optimization" "$test_dir/phy_i2c.rs" \
            -o "$test_out/$chip-$optimization"
        I2C_CASES="$test_out/$chip.bin" I2C_CASE_COUNT="$count" \
            "$test_out/$chip-$optimization"
    done
done
