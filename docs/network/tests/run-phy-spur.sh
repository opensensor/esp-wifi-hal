#!/bin/sh
set -eu
WORK_DIR=$(mktemp -d)
trap 'rm -rf "$WORK_DIR"' EXIT HUP INT TERM
ORACLE=docs/network/tests/phy-spur-oracle
python3 "$ORACLE/test_contract.py"
python3 -O "$ORACLE/test_contract.py"
python3 "$ORACLE/verify_contract.py"
python3 "$ORACLE/generate.py" "$WORK_DIR/cases"
for OPT in 0 2; do
    rustc --edition 2024 --cfg test -C opt-level="$OPT" docs/network/tests/phy_spur.rs -o "$WORK_DIR/host"
    "$WORK_DIR/host" "$WORK_DIR/cases"
done
