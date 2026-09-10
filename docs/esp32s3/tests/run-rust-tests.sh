#!/bin/sh
# Host-only regression checks. Run from any directory; no SDK or board needed.
set -eu
test_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$test_dir/../../.." && pwd)
test_out=$(mktemp -d)
trap 'rm -rf "$test_out"' EXIT HUP INT TERM

cc -std=c11 -O2 -Wall -Wextra -Werror -I"$test_dir" \
    "$test_dir/test_hal.c" -o "$test_out/c-regressions"
"$test_out/c-regressions"
cc -std=c11 -O2 -Wall -Wextra -Werror -I"$test_dir" \
    -c "$test_dir/rust_init_reference.c" -o "$test_out/init-reference.o"
rustc +stable --edition 2024 --test "$test_dir/rust_init.rs" \
    -C "link-arg=$test_out/init-reference.o" -o "$test_out/rust-init"
"$test_out/rust-init"
rustc +stable --edition 2024 --test "$repo_dir/esp-wifi-hal/src/s3_mac_helpers.rs" \
    -o "$test_out/rust-mac-helpers"
"$test_out/rust-mac-helpers"
rustc +stable --edition 2024 --test "$repo_dir/esp-wifi-hal/src/s3_phy.rs" \
    -o "$test_out/rust-phy"
"$test_out/rust-phy"
rustc +stable --edition 2024 --test "$repo_dir/esp-wifi-hal/src/ht20.rs" \
    -o "$test_out/rust-tx"
"$test_out/rust-tx"
rustc +stable --edition 2024 --test "$repo_dir/esp-wifi-hal/src/rx.rs" \
    -o "$test_out/rust-rx"
"$test_out/rust-rx"
rustc +stable --edition 2024 --test --cfg 'feature="esp32s3"' \
    "$test_dir/rust_dma.rs" -o "$test_out/rust-dma"
"$test_out/rust-dma"

rustc +stable --edition 2024 --test --cfg 'feature="esp32c3"' \
    "$test_dir/rust_dma.rs" -o "$test_out/rust-dma-c3"
"$test_out/rust-dma-c3"

sh "$repo_dir/docs/esp32c3/tests/run-tests.sh"
