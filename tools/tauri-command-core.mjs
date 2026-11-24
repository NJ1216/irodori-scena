export const TAURI_DEV_CONFIG = "src-tauri/tauri.dev.conf.json";
export const TAURI_DEV_RUNNER = "../tools/tauri-dev-runner.mjs";

export function tauriInvocation(argv, platform = process.platform) {
  const [command = "dev", ...args] = argv;
  if (command === "build" && platform === "win32") {
    return ["run", "tauri:build:windows", "--", ...args];
  }
  if (command === "build") {
    return ["run", "tauri:build:arm64", "--", ...args];
  }
  if (command === "dev") {
    if (platform === "win32") return ["exec", "tauri", "dev", "--config", TAURI_DEV_CONFIG, "--config", "src-tauri/tauri.windows.conf.json", ...(args.includes("--no-watch") ? [] : ["--no-watch"]), ...args];
    return ["exec", "tauri", "dev", "--config", TAURI_DEV_CONFIG, "--runner", TAURI_DEV_RUNNER, ...args];
  }
  return ["exec", "tauri", command, ...args];
}
