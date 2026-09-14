#!/bin/sh
set -eu
WORK_DIR=$(mktemp -d)
trap 'rm -rf "$WORK_DIR"' EXIT HUP INT TERM
ORACLE=docs/network/tests/phy-rx-gain-cal-oracle
python3 "$ORACLE/test_contract.py"
python3 -O "$ORACLE/test_contract.py"
python3 "$ORACLE/verify_contract.py"
for CHIP in esp32c3 esp32s3; do
    python3 "$ORACLE/generate.py" "$CHIP" "$WORK_DIR/$CHIP.cases"
    for OPT in 0 2; do
        rustc --edition 2024 --cfg test --cfg "$CHIP" -C opt-level="$OPT" docs/network/tests/phy_rx_gain_cal.rs -o "$WORK_DIR/host"
        "$WORK_DIR/host" "$WORK_DIR/$CHIP.cases"
    done
done
