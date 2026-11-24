import { access, constants } from "node:fs/promises";

if (process.env.SCENA_RELEASE_BUILD !== "1") {
  throw new Error("直接の Tauri build は不完全なbundleを作るため禁止されています。`pnpm tauri build` を使用してください。");
}
const suffix = process.platform === "win32" ? ".exe" : "";
const executables = [`src-tauri/binaries/scena-api/scena-api${suffix}`, `src-tauri/resources/environment-manager/uv${suffix}`];
for (const path of executables) await access(path, constants.R_OK | constants.X_OK);
if (process.platform !== "win32") {
  for (const path of ["tools/omlx-sidecar.py", "tools/omlx-runtime-requirements.txt"]) await access(path, constants.R_OK);
}
