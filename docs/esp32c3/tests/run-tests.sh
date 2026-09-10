#!/bin/sh
# Standalone C3 initialization trace regression. No SDK or radio needed.
set -eu
test_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
test_out=$(mktemp -d)
trap 'rm -rf "$test_out"' EXIT HUP INT TERM
rustc +stable --edition 2024 --test "$test_dir/test_c3_mac.rs" -o "$test_out/c3-init"
"$test_out/c3-init"
