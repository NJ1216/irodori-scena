import { spawnSync } from "node:child_process";
import { tauriInvocation } from "./tauri-command-core.mjs";
import { platformPnpmInvocation } from "./windows-build-contract.mjs";

const invocation = tauriInvocation(process.argv.slice(2));
if (process.platform === "win32" && !process.env.npm_execpath) throw new Error("pnpm tauri 経由で実行してください。");
const [command, args] = platformPnpmInvocation(process.platform, process.env.npm_execpath, invocation);
const result = spawnSync(command, args, { stdio: "inherit", env: process.env });
process.exit(result.status ?? 1);
