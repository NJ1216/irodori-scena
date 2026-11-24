#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 WORK_DIRECTORY OUTPUT_ZIP" >&2
  exit 2
fi

work_directory="$1"
output_zip="$2"
source_directory="$work_directory/rhubarb-lip-sync"
build_directory="$work_directory/build"
commit="9b9573cd21b253c9ba58739bbd1aa0b50b991bff"

mkdir -p "$work_directory"
if [[ ! -d "$source_directory/.git" ]]; then
  git clone --filter=blob:none https://github.com/DanielSWolf/rhubarb-lip-sync.git "$source_directory"
fi
git -C "$source_directory" fetch --depth 1 origin "$commit"
git -C "$source_directory" checkout --detach "$commit"

cmake -S "$source_directory" -B "$build_directory" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_OSX_ARCHITECTURES=arm64 \
  -DCMAKE_OSX_DEPLOYMENT_TARGET=11.0
cmake --build "$build_directory" --target rhubarb --config Release
cp "$source_directory/LICENSE.md" "$build_directory/rhubarb/LICENSE.md"
codesign --force --sign - "$build_directory/rhubarb/rhubarb"

UV_CACHE_DIR=.uv-cache uv run python tools/release/package_rhubarb.py \
  --root "$build_directory/rhubarb" \
  --platform darwin-arm64 \
  --commit "$commit" \
  --output "$output_zip"
