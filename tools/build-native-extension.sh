#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
RUSTFLAGS="${RUSTFLAGS:-} -C link-arg=-undefined -C link-arg=dynamic_lookup" \
  cargo build --manifest-path "$root/native/scena-native/Cargo.toml" --release
cp "$root/native/scena-native/target/release/libscena_native.dylib" "$root/scena_native.abi3.so"
if [[ "$(uname -s)" == "Darwin" ]]; then
  codesign --force --sign - "$root/scena_native.abi3.so"
fi
UV_CACHE_DIR="$root/.uv-cache" uv run python -c 'import scena_native; assert callable(scena_native.mix_pcm_members_wav); assert callable(scena_native.render_overlap_wav); assert callable(scena_native.render_timeline_wav)'
