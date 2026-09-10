#!/bin/sh
set -eu
retry_root=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
retry_dir=$(mktemp -d)
trap 'rm -rf "$retry_dir"' EXIT HUP INT TERM
cd "$retry_dir"
export CARGO_TARGET_DIR="$retry_root/target/host-mac-retry"
cargo +stable test --locked --manifest-path "$retry_root/docs/network/tests/mac-retry/Cargo.toml" "$@"
