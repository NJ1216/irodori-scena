import { spawnSync } from "node:child_process";
import { tauriInvocation } from "./tauri-command-core.mjs";

const invocation = tauriInvocation(process.argv.slice(2));
const windows = process.platform === "win32";
if (windows && !process.env.npm_execpath) throw new Error("pnpm tauri 経由で実行してください。");
const result = spawnSync(windows ? process.execPath : "pnpm", windows ? [process.env.npm_execpath, ...invocation] : invocation, { stdio: "inherit", env: process.env });
process.exit(result.status ?? 1);
