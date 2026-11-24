import { spawnSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  REQUIRED_NODE_MAJOR,
  REQUIRED_PNPM_MAJOR,
  REQUIRED_UV_VERSION,
  WINDOWS_TARGET,
  generatedCleanupTargets,
  parseMajor,
  parseUvVersion,
  pnpmInvocation,
  runStage,
  tauriBuildInvocation,
  uvBundleSyncInvocation,
  windowsBuildEnvironmentPaths,
  windowsBuildPaths,
  windowsNativeTargetDir,
} from "./windows-build-contract.mjs";
import { verifyBundledNativeModule } from "./native-extension-output.mjs";

if (process.platform !== "win32") throw new Error("Windows release builds require Windows.");
const root = fileURLToPath(new URL("../", import.meta.url));
const paths = windowsBuildPaths(root);
const packageJson = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));

function execute(command, args, options = {}) {
  const result = spawnSync(command, args, { cwd: root, stdio: "inherit", ...options });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${command} failed (${result.status})`);
}

function capture(command, args) {
  const result = spawnSync(command, args, { cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  if (result.error || result.status !== 0) throw result.error ?? new Error(`${command} failed (${result.status}): ${result.stderr.trim()}`);
  return result.stdout.trim();
}

const [pnpmCommand, pnpmVersionArgs] = pnpmInvocation(process.env.npm_execpath, ["--version"]);
runStage("1/7 環境確認", "docs/public/windows-development.md の固定バージョンと Visual Studio Build Tools 構成を確認してください。", () => {
  if (parseMajor(process.version) !== REQUIRED_NODE_MAJOR) throw new Error(`Node.js ${REQUIRED_NODE_MAJOR}.x が必要です: ${process.version}`);
  const pnpmVersion = capture(pnpmCommand, pnpmVersionArgs);
  if (parseMajor(pnpmVersion) !== REQUIRED_PNPM_MAJOR) throw new Error(`pnpm ${REQUIRED_PNPM_MAJOR}.x が必要です: ${pnpmVersion}`);
  const uvVersion = capture("uv", ["--version"]);
  if (parseUvVersion(uvVersion) !== REQUIRED_UV_VERSION) throw new Error(`uv ${REQUIRED_UV_VERSION} が必要です: ${uvVersion}`);
  const rust = capture("rustc", ["-vV"]);
  if (!rust.includes(`host: ${WINDOWS_TARGET}`)) throw new Error(`Rust MSVC host ${WINDOWS_TARGET} が必要です。`);
  const vswhere = join(process.env["ProgramFiles(x86)"] ?? "", "Microsoft Visual Studio", "Installer", "vswhere.exe");
  if (!existsSync(vswhere)) throw new Error("Visual Studio Installer の vswhere.exe が見つかりません。");
  const visualStudio = capture(vswhere, ["-latest", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "Microsoft.VisualStudio.Component.Windows11SDK.26100", "-property", "installationPath"]);
  if (!visualStudio) throw new Error("Visual Studio C++ Build Tools または Windows 11 SDK 26100 が不足しています。");
});

const temporary = join(process.env.TEMP ?? root, `scena-pyinstaller-${process.pid}`);
const buildEnvironment = windowsBuildEnvironmentPaths(temporary);
mkdirSync(dirname(paths.apiBundle), { recursive: true });
const bundleEnv = { ...process.env, PYINSTALLER_CONFIG_DIR: join(temporary, "config"), UV_CACHE_DIR: join(root, ".uv-cache"), UV_PROJECT_ENVIRONMENT: buildEnvironment.environment, SCENA_NATIVE_MODULE_DIR: join(temporary, "native") };
try {
  for (const target of generatedCleanupTargets(root)) rmSync(target, { recursive: true, force: true });
  const buildStartedAt = Date.now();

  runStage("2/7 Windows Python 環境", "uv.lock と固定 Python を確認してください。リリースビルドは共有 .venv を使用しません。", () => {
    execute("uv", uvBundleSyncInvocation("3.13.12"), { env: bundleEnv });
  });

  runStage("3/7 native 拡張", "Rust MSVC toolchain と C++ Build Tools を確認し、表示された native build エラーを解消してください。", () => {
    execute("node", ["tools/build-native-extension.mjs"], { env: { ...bundleEnv, CARGO_TARGET_DIR: windowsNativeTargetDir(root), SCENA_BUILD_PYTHON: buildEnvironment.python } });
  });

  runStage("4/7 PyInstaller", "uv.lock と tools/pyinstaller/scena-api.spec を確認し、同じエラーを契約テストへ追加してください。", () => {
    execute(buildEnvironment.pyinstaller, ["--noconfirm", "--clean", "--distpath", "src-tauri/binaries", "--workpath", join(temporary, "work"), "tools/pyinstaller/scena-api.spec"], { env: bundleEnv });
  });

  runStage("5/7 同梱物監査", "不足した worker・catalogue または禁止依存を spec で修正し、監査の回帰テストを追加してください。", () => {
    verifyBundledNativeModule(join(bundleEnv.SCENA_NATIVE_MODULE_DIR, "scena_native.pyd"), join(paths.apiBundle, "_internal", "scena_native.pyd"));
    execute(buildEnvironment.python, ["tools/audit-pyinstaller-bundle.py", "src-tauri/binaries/scena-api", "--max-bytes", "100663296"], { env: bundleEnv });
    const uv = capture("where.exe", ["uv.exe"]).split(/\r?\n/)[0];
    mkdirSync(dirname(paths.bundledUv), { recursive: true });
    copyFileSync(uv, paths.bundledUv);
  });

  runStage("6/7 Tauri/NSIS", "NSIS設定、Windows SDK、WebView2取得経路を確認してください。再実行前の成果物削除は自動です。", () => {
    const [command, args] = tauriBuildInvocation(process.env.npm_execpath, process.argv.slice(2));
    execute(command, args, { env: { ...process.env, SCENA_RELEASE_BUILD: "1", PATH: `${dirname(paths.bundledUv)};${process.env.PATH}` } });
  });

  runStage("7/7 最終監査", "現在バージョンのNSIS 1本、同梱ファイル、GUI subsystem、サイズ上限を確認してください。", () => {
    execute("node", ["tools/verify-windows-release.mjs", "--version", packageJson.version, "--started-at", String(buildStartedAt)]);
  });
} finally {
  rmSync(temporary, { recursive: true, force: true });
}
