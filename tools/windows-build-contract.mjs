import { join, win32 } from "node:path";

export const WINDOWS_TARGET = "x86_64-pc-windows-msvc";
// Node.js and pnpm track the latest releases; only these minimum major versions are required.
export const MINIMUM_NODE_MAJOR = 24;
export const MINIMUM_PNPM_MAJOR = 11;
export const REQUIRED_UV_VERSION = "0.12.5";

export function runnerBootstrapScript(workflow) {
  const stage = workflow.replace(/\r\n?/g, "\n").split("- name: Restore installed tool paths")[1]?.split("- name: Checkout the immutable tag")[0];
  const script = stage?.split("run: |\n")[1];
  if (!script) throw new Error("Missing runner bootstrap run block");
  return script
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => line.slice(10))
    .join("\n");
}

export function windowsPythonContractInvocation(suites) {
  // Match uv.lock, but isolate these lightweight contracts from an absent .venv.
  return ["run", "--no-project", "--python", "3.13.12", "--with", "packaging==26.3", "python", "-m", "unittest", ...suites];
}

export function windowsBuildPaths(root) {
  const release = join(root, "src-tauri", "target", WINDOWS_TARGET, "release");
  return {
    apiBundle: join(root, "src-tauri", "binaries", "scena-api"),
    bundledUv: join(root, "src-tauri", "resources", "environment-manager", "uv.exe"),
    nsisOutput: join(release, "bundle", "nsis"),
    release,
  };
}

export function windowsBuildEnvironmentPaths(temporary) {
  const environment = win32.join(temporary, "environment");
  return {
    environment,
    pyinstaller: win32.join(environment, "Scripts", "pyinstaller.exe"),
    python: win32.join(environment, "Scripts", "python.exe"),
  };
}

export function windowsNativeTargetDir(root) {
  return win32.join(root, "native", "scena-native", "target", WINDOWS_TARGET);
}

export function uvBundleSyncInvocation(pythonVersion) {
  return ["sync", "--locked", "--no-dev", "--group", "bundle", "--no-install-project", "--python", pythonVersion];
}

export function generatedCleanupTargets(root) {
  const paths = windowsBuildPaths(root);
  return [paths.apiBundle, paths.bundledUv, paths.nsisOutput];
}

export function pnpmInvocation(npmExecPath, args) {
  if (!npmExecPath) throw new Error("pnpm 経由で `pnpm.cmd tauri build` を実行してください。");
  // pnpm 12 ships a standalone pnpm.exe; older releases point npm_execpath at a pnpm.cjs script for Node.
  if (/\.exe$/i.test(npmExecPath)) return [npmExecPath, [...args]];
  return [process.execPath, [npmExecPath, ...args]];
}

export function platformPnpmInvocation(platform, npmExecPath, args) {
  return platform === "win32" ? pnpmInvocation(npmExecPath, args) : ["pnpm", args];
}

export function tauriBuildInvocation(npmExecPath, forwarded = []) {
  return pnpmInvocation(npmExecPath, ["exec", "tauri", "build", "--target", WINDOWS_TARGET, "--bundles", "nsis", "--config", "src-tauri/tauri.windows.release.conf.json", ...forwarded.filter((argument) => argument !== "--")]);
}

export function expectedInstallerName(productName, version) {
  return `${productName}_${version}_x64-setup.exe`;
}

export function inspectInstallerEntries(entries, { productName, version, buildStartedAt }) {
  const installers = entries.filter((entry) => entry.name.endsWith("-setup.exe"));
  const expected = expectedInstallerName(productName, version);
  const problems = [];
  if (installers.length !== 1) problems.push(`NSISインストーラーは1本必要ですが、${installers.length}本ありました。`);
  if (installers.length === 1 && installers[0].name !== expected) {
    problems.push(`現在バージョンの成果物 ${expected} ではなく ${installers[0].name} がありました。`);
  }
  if (installers.length === 1 && installers[0].mtimeMs < buildStartedAt) {
    problems.push(`${installers[0].name} は今回のビルド開始前に生成された成果物です。`);
  }
  const unexpected = entries.filter((entry) => !entry.name.endsWith("-setup.exe"));
  if (unexpected.length) problems.push(`NSIS出力に想定外の項目があります: ${unexpected.map((entry) => entry.name).join(", ")}`);
  return { installer: problems.length === 0 ? installers[0] : null, problems };
}

export function parseMajor(versionOutput) {
  const match = versionOutput.match(/(?:^|\s)v?(\d+)(?:\.|$)/);
  return match ? Number(match[1]) : null;
}

export function meetsMinimumMajor(versionOutput, minimum) {
  const major = parseMajor(versionOutput);
  return major !== null && major >= minimum;
}

export function parseUvVersion(versionOutput) {
  return versionOutput.match(/^uv\s+(\d+\.\d+\.\d+)(?:\s|$)/)?.[1] ?? null;
}

export function runStage(name, remedy, action, reporter = console) {
  reporter.log(`\n[Windows build] ${name}`);
  try {
    return action();
  } catch (error) {
    reporter.error(`[Windows build] ${name} に失敗しました。`);
    reporter.error(`対処: ${remedy}`);
    throw error;
  }
}
