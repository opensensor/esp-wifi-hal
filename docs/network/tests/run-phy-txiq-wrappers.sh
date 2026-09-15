#!/bin/sh
set -eu
ORACLE=docs/network/tests/phy-txiq-wrappers-oracle
python3 "$ORACLE/test_contract.py"
python3 -O "$ORACLE/test_contract.py"
python3 "$ORACLE/verify.py"
python3 -O "$ORACLE/verify.py"
python3 "$ORACLE/host_compare.py"
