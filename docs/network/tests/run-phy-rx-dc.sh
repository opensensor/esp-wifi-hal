#!/bin/sh
set -eu
test_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT HUP INT TERM
python3 -m unittest discover -s "$test_dir/phy-rx-dc-oracle" -q
python3 -O -m unittest discover -s "$test_dir/phy-rx-dc-oracle" -q
python3 "$test_dir/phy-rx-dc-oracle/verify_contract.py"
for chip in esp32c3 esp32s3; do
 python3 "$test_dir/phy-rx-dc-oracle/generate.py" "$chip" "$out/$chip.bin"
 for optimization in 0 2; do
  rustc +stable --edition 2024 --cfg "$chip" -C "opt-level=$optimization" "$test_dir/phy_rx_dc.rs" -o "$out/$chip-$optimization"
  "$out/$chip-$optimization" "$out/$chip.bin"
 done
done
