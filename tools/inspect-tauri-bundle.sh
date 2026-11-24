#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd -P)"
app="$root/src-tauri/target/aarch64-apple-darwin/release/bundle/macos/irodori SCENA.app"
api="$app/Contents/Resources/scena-api-runtime/scena-api"
main="$app/Contents/MacOS/irodori-scena"

test -x "$api"
test -x "$main"
test ! -e "$app/Contents/Resources/omlx-runtime"
test -f "$app/Contents/Resources/omlx-bootstrap/requirements.txt"
test -f "$app/Contents/Resources/ja.lproj/InfoPlist.strings"
test -f "$app/Contents/Resources/scena-api-runtime/_internal/server/catalogs/rhubarb-runtime.json"
test -f "$app/Contents/Resources/scena-api-runtime/_internal/server/mlx_irodori_worker.py"
file "$api" "$main" | grep -q "arm64"
codesign --verify --deep --strict "$app"
uv run --with pyinstaller python "$root/tools/audit-pyinstaller-bundle.py" \
  "$app/Contents/Resources/scena-api-runtime" --max-bytes 67108864
du -sh "$app"
dmg_dir="$root/src-tauri/target/aarch64-apple-darwin/release/bundle/dmg"
if test -d "$dmg_dir"; then
  du -sh "$dmg_dir"/*.dmg
fi
test ! -d "$root/build"
if find "$root" -maxdepth 1 -name '*.spec' -print -quit | grep -q .; then
  echo "repository-root PyInstaller spec remains after build" >&2
  exit 1
fi

# The app is an intermediate input to the DMG, not a second distribution.
# Preserve it if auditing or DMG verification fails, or if it is running.
version="$(node -p "require(process.argv[1]).version" "$root/package.json")"
dmg="$dmg_dir/irodori SCENA_${version}_aarch64.dmg"
test -s "$dmg"
hdiutil verify "$dmg"
test ! -L "$app"
processes="$(ps -axo comm)"
if [[ "$processes" == *"$app/"* ]]; then
  echo "generated app is running; intermediate bundle was retained" >&2
  exit 1
fi
distribution="$dmg_dir/irodori SCENA_${version}_AppleSilicon.dmg"
if test -e "$distribution" || test -L "$distribution"; then
  echo "AppleSilicon DMG already exists; refusing to replace it" >&2
  exit 1
fi
mv -n "$dmg" "$distribution"
test ! -e "$dmg"
dmg="$distribution"
rm -rf "$app"
echo "Removed intermediate .app; verified DMG retained: $dmg"
