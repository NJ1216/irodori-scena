#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$root/.uv-cache}"
uv_version="$(uv --version)"
if [[ ! "$uv_version" =~ ^uv\ 0\.12\.5([[:space:]]|$) ]]; then
  if [[ "${SCENA_PINNED_BUILD_UV:-}" == 1 ]]; then
    echo "Unable to activate required uv 0.12.5 (got $uv_version)" >&2
    exit 1
  fi
  echo "Preparing uv 0.12.5 for this build (host: $uv_version)" >&2
  export SCENA_PINNED_BUILD_UV=1
  exec uv run --no-project --python 3.13.12 --with uv==0.12.5 \
    bash "$root/tools/build-tauri-sidecar.sh" "$@"
fi
# The pinned uv comes from an ephemeral "uv run" environment; its VIRTUAL_ENV is not
# the project environment and would only make each project command warn.
unset VIRTUAL_ENV
bash "$root/tools/build-native-extension.sh"
output="$root/src-tauri/binaries/scena-api"
pyinstaller_temp="$(mktemp -d "${TMPDIR:-/tmp}/scena-pyinstaller.XXXXXX")"
trap 'rm -rf "$pyinstaller_temp"' EXIT
export PYINSTALLER_CONFIG_DIR="$pyinstaller_temp/config"
mkdir -p "$root/src-tauri/binaries"
uv run --locked --group bundle pyinstaller --noconfirm --clean \
  --distpath "$root/src-tauri/binaries" --workpath "$pyinstaller_temp/api-work" \
  "$root/tools/pyinstaller/scena-api.spec"
test -x "$output/scena-api"
uv run --locked --group bundle python "$root/tools/audit-pyinstaller-bundle.py" \
  "$output" --max-bytes 67108864

environment_manager="$root/src-tauri/resources/environment-manager"
mkdir -p "$environment_manager"
cp "$(command -v uv)" "$environment_manager/uv"
chmod 755 "$environment_manager/uv"
