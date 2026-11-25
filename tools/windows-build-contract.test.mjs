import assert from "node:assert/strict";
import { copyFileSync, existsSync, mkdtempSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import test from "node:test";
import { spawnSync } from "node:child_process";
import {
  expectedInstallerName,
  generatedCleanupTargets,
  inspectInstallerEntries,
  MINIMUM_NODE_MAJOR,
  MINIMUM_PNPM_MAJOR,
  meetsMinimumMajor,
  parseUvVersion,
  platformPnpmInvocation,
  pnpmInvocation,
  runnerBootstrapScript,
  runStage,
  tauriBuildInvocation,
  uvBundleSyncInvocation,
  windowsBuildEnvironmentPaths,
  windowsBuildPaths,
  windowsNativeTargetDir,
  windowsPythonContractInvocation,
} from "./windows-build-contract.mjs";

const metadata = { productName: "irodori SCENA", version: "26.9.13" };
const entry = (name, mtimeMs = 200) => ({ name, mtimeMs });
const root = new URL("../", import.meta.url);
const read = (path) => readFileSync(new URL(path, root), "utf8");
// Private Gitea workflows are intentionally absent from the public source export.
const hasInternalWorkflow = existsSync(new URL(".gitea/workflows/internal-release.yml", root));

test("clean runner setup bootstraps Node before npm and preserves tool discovery across jobs", { skip: !hasInternalWorkflow }, () => {
  const setup = read("tools/release/setup-windows-runner.ps1");
  const gate = setup.indexOf("if (!$Apply) { $plan; return }");
  assert.ok(gate > 0 && gate < setup.indexOf("Start-Process msiexec.exe"));
  assert.ok(setup.indexOf("Get-FileHash $download") < setup.indexOf("Start-Process msiexec.exe"));
  assert.ok(setup.indexOf("Start-Process msiexec.exe") < setup.indexOf("Invoke-Checked 'npm.cmd'"));
  assert.match(setup, /SHASUMS256\.txt/);
  assert.match(setup, /checksum mismatch/);
  assert.match(setup, /SetEnvironmentVariable\('Path', \(\$entries -join ';'\), 'User'\)/);
  assert.match(setup, /@\(\$prefix, \$cargoBin\)/);
  assert.match(setup, /Windows11SDK\.26100/);
  assert.match(setup, /if \(\$LASTEXITCODE -ne 0\) \{ throw/);
  assert.doesNotMatch(setup, /Restart-Computer|Restart-Service|Set-ExecutionPolicy|GITEA_TOKEN|credential/);
});

test("Windows runner setup parses and prints its plan without winget or Node", { skip: process.platform !== "win32" || !hasInternalWorkflow }, () => {
  const powershell = join(process.env.SystemRoot, "System32", "WindowsPowerShell", "v1.0", "powershell.exe");
  const setup = new URL("tools/release/setup-windows-runner.ps1", root);
  const result = spawnSync(powershell, ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", decodeURIComponent(setup.pathname).replace(/^\//, "")], {
    encoding: "utf8",
    env: { ...process.env, PATH: join(process.env.SystemRoot, "System32") },
  });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /Node\.js latest LTS/);
  assert.match(result.stdout, /Visual Studio/);
  assert.match(result.stdout, /\.NET SDK 10/);
});

test("restores stale runner PATH before checkout without installing tools", { skip: !hasInternalWorkflow }, () => {
  const workflow = read(".gitea/workflows/internal-release.yml");
  const bootstrap = workflow.indexOf("- name: Restore installed tool paths");
  const checkout = workflow.indexOf("- name: Checkout the immutable tag");
  assert.ok(bootstrap >= 0 && bootstrap < checkout, "Node PATH must be repaired before the JavaScript action");
  const stage = workflow.slice(bootstrap, checkout);
  assert.match(stage, /shell: powershell/);
  assert.match(stage, /GetEnvironmentVariable\('PATH', 'Machine'\)/);
  assert.match(stage, /GetEnvironmentVariable\('PATH', 'User'\)/);
  assert.match(stage, /AppendAllLines\(\$env:GITHUB_PATH/);
  assert.doesNotMatch(stage, /SetEnvironmentVariable|winget install|choco install|npm install/);
});

test("manual Windows check runs only on dispatch and never interpolates inputs into scripts", { skip: !hasInternalWorkflow }, () => {
  const workflow = read(".gitea/workflows/windows-check.yml");
  const trigger = workflow.slice(workflow.indexOf("\non:"), workflow.indexOf("\npermissions:"));
  assert.match(trigger, /workflow_dispatch:/);
  assert.doesNotMatch(trigger, /\n {2}(push|pull_request|schedule):/);
  const bootstrap = workflow.indexOf("- name: Restore installed tool paths");
  assert.ok(bootstrap >= 0 && bootstrap < workflow.indexOf("uses: actions/checkout"), "Node PATH must be repaired before the JavaScript action");
  for (const block of workflow.split(/\n\s+run: \|/).slice(1)) {
    const script = block.split(/\n\s+- name:/)[0];
    assert.doesNotMatch(script, /\$\{\{\s*inputs\./, "inputs must reach scripts through env, not template expansion");
  }
  assert.doesNotMatch(workflow, /SetEnvironmentVariable|winget install|choco install|tauri:build/);
});

test("Windows bootstrap recovers node for subsequent steps from a runner PATH without node", { skip: process.platform !== "win32" || !hasInternalWorkflow }, () => {
  const workflow = read(".gitea/workflows/internal-release.yml");
  const script = runnerBootstrapScript(workflow);
  const temporary = mkdtempSync(join(tmpdir(), "scena-runner-path-"));
  try {
    const pathFile = join(temporary, "job-path.txt");
    writeFileSync(pathFile, "");
    const systemRoot = process.env.SystemRoot || "C:\\Windows";
    const oldPath = join(systemRoot, "System32");
    const powershell = join(oldPath, "WindowsPowerShell", "v1.0", "powershell.exe");
    const missing = spawnSync(powershell, ["-NoProfile", "-NonInteractive", "-Command", "if (Get-Command node -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }"], { env: { ...process.env, PATH: oldPath } });
    assert.equal(missing.status, 0, "The reproducing runner PATH must lack node");
    const result = spawnSync(powershell, ["-NoProfile", "-NonInteractive", "-Command", script], {
      encoding: "utf8",
      env: { ...process.env, PATH: oldPath, GITHUB_PATH: pathFile },
    });
    assert.equal(result.status, 0, result.stderr || result.error?.message);
    const restoredPath = readFileSync(pathFile, "utf8").trim().split(/\r?\n/).join(";");
    assert.ok(restoredPath && !restoredPath.startsWith("\uFEFF"), "Actions PATH must contain UTF-8 without a BOM");
    const node = spawnSync(powershell, ["-NoProfile", "-NonInteractive", "-Command", "node --version"], { encoding: "utf8", env: { ...process.env, PATH: restoredPath + ";" + oldPath } });
    assert.equal(node.status, 0, node.stderr || node.error?.message);
    assert.match(node.stdout, /^v\d+\./);
  } finally {
    rmSync(temporary, { recursive: true, force: true });
  }
});

test("Japanese worker and ORT guard reproduced Windows packaging and runtime build failures", () => {
  // The private, unadopted ORT experiment is absent from the public source export.
  // If either source or contract is present, both must be present and tested.
  const ortSource = existsSync(new URL("tools/release/build_onnxruntime_mac_parity.py", root));
  const ortContract = existsSync(new URL("tests/test_onnxruntime_parity_build.py", root));
  assert.equal(ortSource, ortContract, "ORT experiment source and regression contract must stay together");
  const suites = ["tests.test_japanese_worker_build"];
  if (ortSource) suites.push("tests.test_onnxruntime_parity_build");
  const temporary = mkdtempSync(join(tmpdir(), "scena-clean-python-contract-"));
  try {
    const sources = ["tests/test_japanese_worker_build.py", "tools/release/build_japanese_lipsync.py", "tools/release/license_sources.py"];
    if (ortSource) sources.push("tests/test_onnxruntime_parity_build.py", "tools/release/build_onnxruntime_mac_parity.py", "tools/release/prepare_onnxruntime_mac_parity.py");
    for (const source of sources) {
      const destination = join(temporary, source);
      mkdirSync(dirname(destination), { recursive: true });
      copyFileSync(new URL(source, root), destination);
    }
    writeFileSync(join(temporary, "tests", "__init__.py"), "");
    const result = spawnSync("uv", windowsPythonContractInvocation(suites), {
      cwd: temporary,
      encoding: "utf8",
      timeout: 30000,
      env: { ...process.env, UV_CACHE_DIR: join(tmpdir(), "scena-japanese-worker-contract-uv-cache") },
    });
    assert.equal(result.status, 0, result.stderr || result.error?.message);
    assert.equal(existsSync(join(temporary, ".venv")), false, "Contract tests must work without creating or relying on a project environment");
  } finally {
    rmSync(temporary, { recursive: true, force: true });
  }
});

test("runner bootstrap extraction accepts LF and Windows CRLF without truncating PowerShell", () => {
  const lf = "- name: Restore installed tool paths before JavaScript checkout\n        run: |\n          $ErrorActionPreference = 'Stop'\n          node --version\n      - name: Checkout the immutable tag\n";
  const expected = "$ErrorActionPreference = 'Stop'\nnode --version";
  assert.equal(runnerBootstrapScript(lf), expected);
  assert.equal(runnerBootstrapScript(lf.replaceAll("\n", "\r\n")), expected);
  assert.throws(() => runnerBootstrapScript("run: not a bootstrap"), /Missing runner bootstrap/);
});

test("Windows Python contracts provide their locked dependency without a project environment", () => {
  const args = windowsPythonContractInvocation(["tests.test_japanese_worker_build"]);
  assert.ok(args.includes("--no-project"));
  assert.ok(!args.includes("--no-sync"));
  assert.equal(args[args.indexOf("--with") + 1], "packaging==26.3");
  assert.match(read("uv.lock"), /name = "packaging"\r?\nversion = "26\.3"/);
});

test("removes only generated Windows outputs including stale installers", () => {
  const root = mkdtempSync(join(tmpdir(), "scena-windows-contract-"));
  const paths = windowsBuildPaths(root);
  mkdirSync(paths.apiBundle, { recursive: true });
  mkdirSync(join(paths.bundledUv, ".."), { recursive: true });
  mkdirSync(paths.nsisOutput, { recursive: true });
  writeFileSync(join(paths.apiBundle, "scena-api.exe"), "old");
  writeFileSync(paths.bundledUv, "old");
  writeFileSync(join(paths.nsisOutput, "irodori SCENA_26.9.12_x64-setup.exe"), "old");
  writeFileSync(join(paths.nsisOutput, expectedInstallerName(metadata.productName, metadata.version)), "old");
  for (const target of generatedCleanupTargets(root)) rmSync(target, { recursive: true, force: true });
  assert.equal(readdirSync(join(root, "src-tauri", "binaries")).length, 0);
  assert.equal(readdirSync(join(root, "src-tauri", "resources", "environment-manager")).length, 0);
  assert.equal(statSync(join(root, "src-tauri", "target")).isDirectory(), true);
  assert.equal(readdirSync(join(paths.nsisOutput, "..")).includes("nsis"), false);
});

test("builds pnpm and Tauri commands without relying on pnpm.cmd lookup", () => {
  assert.deepEqual(pnpmInvocation("C:\\pnpm\\pnpm.cjs", ["--version"]), [process.execPath, ["C:\\pnpm\\pnpm.cjs", "--version"]]);
  assert.deepEqual(tauriBuildInvocation("C:\\pnpm\\pnpm.cjs", ["--", "--verbose"])[1].slice(-2), ["src-tauri/tauri.windows.release.conf.json", "--verbose"]);
  assert.throws(() => pnpmInvocation(undefined, []), /pnpm\.cmd tauri build/);
});

test("runs the standalone pnpm 12 executable directly instead of loading it into Node", () => {
  const pnpmExe = "C:\\Users\\runner\\AppData\\Local\\tools\\node_modules\\pnpm\\pnpm.exe";
  assert.deepEqual(pnpmInvocation(pnpmExe, ["--version"]), [pnpmExe, ["--version"]]);
  assert.deepEqual(pnpmInvocation("C:\\pnpm\\PNPM.EXE", ["exec", "tauri"]), ["C:\\pnpm\\PNPM.EXE", ["exec", "tauri"]]);
  const [command, args] = tauriBuildInvocation(pnpmExe, []);
  assert.equal(command, pnpmExe);
  assert.deepEqual(args.slice(0, 3), ["exec", "tauri", "build"]);
  assert.deepEqual(platformPnpmInvocation("win32", pnpmExe, ["exec", "vite"]), [pnpmExe, ["exec", "vite"]]);
});

test("starts the Playwright Vite server through pnpm's resolved Windows script", () => {
  const args = ["dev:web", "--port", "5174"];
  assert.deepEqual(platformPnpmInvocation("win32", "C:\\pnpm\\pnpm.cjs", args), [process.execPath, ["C:\\pnpm\\pnpm.cjs", ...args]]);
  assert.deepEqual(platformPnpmInvocation("darwin", undefined, args), ["pnpm", args]);
  assert.deepEqual(platformPnpmInvocation("linux", undefined, args), ["pnpm", args]);
});

test("accepts current Node.js and pnpm releases at or above the minimum major versions", () => {
  assert.equal(MINIMUM_NODE_MAJOR, 24);
  assert.equal(MINIMUM_PNPM_MAJOR, 11);
  for (const version of ["v24.21.0", "v26.13.1", "v30.0.0"]) assert.equal(meetsMinimumMajor(version, MINIMUM_NODE_MAJOR), true, version);
  for (const version of ["11.22.0", "12.23.0"]) assert.equal(meetsMinimumMajor(version, MINIMUM_PNPM_MAJOR), true, version);
  for (const version of ["v22.11.0", "10.13.1", "", "not a version"]) assert.equal(meetsMinimumMajor(version, version.startsWith("v") ? MINIMUM_NODE_MAJOR : MINIMUM_PNPM_MAJOR), false, version);
});

test("parses the uv version without rejecting official build metadata", () => {
  assert.equal(parseUvVersion("uv 0.12.5"), "0.12.5");
  assert.equal(parseUvVersion("uv 0.12.5 (210d1f678 2026-08-14 x86_64-pc-windows-msvc)"), "0.12.5");
  assert.equal(parseUvVersion("uv 0.12.4 (older)"), "0.12.4");
  assert.equal(parseUvVersion("uv 0.12.50"), "0.12.50");
  assert.equal(parseUvVersion("uv 0.12"), null);
  assert.equal(parseUvVersion("unrecognized 0.12.5"), null);
});

test("isolates Windows release Python and native artifacts from macOS development state", () => {
  const paths = windowsBuildEnvironmentPaths("C:\\Temp\\scena-build");
  assert.equal(paths.python, "C:\\Temp\\scena-build\\environment\\Scripts\\python.exe");
  assert.equal(paths.pyinstaller, "C:\\Temp\\scena-build\\environment\\Scripts\\pyinstaller.exe");
  assert.equal(windowsNativeTargetDir("D:\\repo"), "D:\\repo\\native\\scena-native\\target\\x86_64-pc-windows-msvc");
  assert.deepEqual(uvBundleSyncInvocation("3.13.12"), ["sync", "--locked", "--no-dev", "--group", "bundle", "--no-install-project", "--python", "3.13.12"]);
  const buildScript = read("tools/build-windows-release.mjs");
  assert.match(buildScript, /SCENA_BUILD_PYTHON: buildEnvironment\.python/);
  assert.match(buildScript, /SCENA_NATIVE_MODULE_DIR: join\(temporary, "native"\)/);
  assert.match(buildScript, /verifyBundledNativeModule\(/);
  assert.match(buildScript, /execute\(buildEnvironment\.pyinstaller/);
  assert.doesNotMatch(buildScript, /execute\("uv", \["run"/);
  const nativeBuild = read("tools/build-native-extension.mjs");
  assert.match(nativeBuild, /process\.env\.SCENA_NATIVE_MODULE_DIR \?\? root/);
  assert.match(nativeBuild, /cwd: outputDirectory/);
  const pyinstallerSpec = read("tools/pyinstaller/scena-api.spec");
  assert.match(pyinstallerSpec, /SCENA_NATIVE_MODULE_DIR"\) if sys\.platform == "win32" else None/);
  assert.match(pyinstallerSpec, /pathex=\(\[str\(native_module\.parent\)\]/);
  assert.match(pyinstallerSpec, /PyInstaller must collect the isolated native module/);
});

test("accepts exactly one current installer created after this build started", () => {
  const result = inspectInstallerEntries([entry(expectedInstallerName(metadata.productName, metadata.version))], { ...metadata, buildStartedAt: 100 });
  assert.equal(result.problems.length, 0);
});

test("rejects empty, stale, duplicate, old-version, and unexpected NSIS outputs", () => {
  assert.notEqual(inspectInstallerEntries([], { ...metadata, buildStartedAt: 100 }).problems.length, 0);
  assert.notEqual(inspectInstallerEntries([entry(expectedInstallerName(metadata.productName, metadata.version), 99)], { ...metadata, buildStartedAt: 100 }).problems.length, 0);
  assert.notEqual(inspectInstallerEntries([entry(expectedInstallerName(metadata.productName, metadata.version)), entry("copy-setup.exe")], { ...metadata, buildStartedAt: 100 }).problems.length, 0);
  assert.notEqual(inspectInstallerEntries([entry("irodori SCENA_26.9.12_x64-setup.exe")], { ...metadata, buildStartedAt: 100 }).problems.length, 0);
  assert.notEqual(inspectInstallerEntries([entry(expectedInstallerName(metadata.productName, metadata.version)), entry("trace.log")], { ...metadata, buildStartedAt: 100 }).problems.length, 0);
});

test("reports the failed stage and its remedy without hiding the original failure", () => {
  const messages = [];
  const failure = new Error("fixture failure");
  const reporter = { log: (message) => messages.push(message), error: (message) => messages.push(message) };
  assert.throws(
    () =>
      runStage(
        "3/6 PyInstaller",
        "specを確認",
        () => {
          throw failure;
        },
        reporter,
      ),
    (error) => error === failure,
  );
  assert.equal(
    messages.some((message) => message.includes("PyInstaller に失敗")),
    true,
  );
  assert.equal(
    messages.some((message) => message.includes("対処: specを確認")),
    true,
  );
});

test("keeps the Windows packaging, sidecar, and GUI-subsystem contract", () => {
  const packageJson = JSON.parse(read("package.json"));
  const tauri = JSON.parse(read("src-tauri/tauri.conf.json"));
  const release = JSON.parse(read("release-metadata.json"));
  const windows = JSON.parse(read("src-tauri/tauri.windows.release.conf.json"));
  const cargoVersion = read("src-tauri/Cargo.toml").match(/^version = "([^"]+)"/m)?.[1];
  assert.equal(packageJson.scripts["tauri:build:windows"], "node tools/build-windows-release.mjs");
  assert.equal(packageJson.version, tauri.version);
  assert.equal(packageJson.version, cargoVersion);
  assert.equal(packageJson.version, release.version);
  assert.deepEqual(windows.bundle.targets, ["nsis"]);
  assert.equal(windows.bundle.windows.nsis.template, "windows/installer.nsi");
  assert.equal(windows.bundle.windows.nsis.installerHooks, "windows/installer-hooks.nsh");
  assert.equal(JSON.stringify(windows).includes("omlx"), false);
  assert.deepEqual(
    tauri.bundle.fileAssociations.map(({ ext, name }) => ({ ext, name })),
    [
      { ext: ["scena"], name: "SCENA Project" },
      { ext: ["scenacast"], name: "SCENA Cast" },
    ],
  );
  const spec = read("tools/pyinstaller/scena-api.spec");
  for (const required of ["irodori_worker.py", "irodori_host.py", "irodori_acceleration_adapter.py", "irodori_acceleration_sampler.py", "irodori_cuda_calibration.py", "irodori_cuda_graphs.py", "rhubarb-runtime.json", "llama-cpp-runtime.json"]) {
    assert.match(spec, new RegExp(required.replace(".", "\\.")));
  }
  assert.match(read("tools/verify-windows-release.mjs"), /server\/catalogs\/rhubarb-runtime\.json/);
  const installerHooks = read("src-tauri/windows/installer-hooks.nsh");
  const installerTemplate = read("src-tauri/windows/installer.nsi");
  assert.match(installerTemplate, /APP_ASSOCIATE/);
  assert.match(installerTemplate, /APP_UNASSOCIATE/);
  assert.match(installerHooks, /--cleanup-user-data --error-log/);
  assert.doesNotMatch(installerHooks, /--data-root|--webview-root|\$APPDATA|\$LOCALAPPDATA/);
  assert.match(spec, /console=sys\.platform != "win32"/);
  assert.match(read("src-tauri/src/main.rs"), /windows_subsystem = "windows"/);
  const devAppProbe = read("tools/windows-dev/verify-dev-app.ps1");
  assert.match(devAppProbe, /GetDpiForWindow/);
  assert.match(devAppProbe, /GetWindowDpiAwarenessContext/);
  assert.match(devAppProbe, /AreDpiAwarenessContextsEqual/);
  assert.match(devAppProbe, /\[IntPtr\]\(-4\)/);
  assert.match(devAppProbe, /development window is not Per-Monitor V2 DPI aware/);
  assert.match(read("tools/build-windows-release.mjs"), /tauriBuildInvocation\(process\.env\.npm_execpath/);
});

test("packages every direct import used by the external TTS worker", () => {
  const worker = read("server/irodori_worker.py");
  const spec = read("tools/pyinstaller/scena-api.spec");
  const release = read("tools/verify-windows-release.mjs");
  const imports = [...worker.matchAll(/^from (irodori_[a-z_]+) import /gm)].map((match) => match[1]);
  assert.ok(imports.includes("irodori_load_adapter"));
  for (const moduleName of imports) {
    assert.ok(spec.includes(`ROOT / "server" / "${moduleName}.py"`), `PyInstaller is missing ${moduleName}.py`);
    assert.ok(release.includes(`_internal/server/${moduleName}.py`), `Windows release audit is missing ${moduleName}.py`);
  }
});

test("public Windows release runs only on v tags and only drafts its own release", () => {
  const workflow = read(".github/workflows/windows-release.yml");
  const trigger = workflow.slice(workflow.indexOf("\non:"), workflow.indexOf("\npermissions:"));
  assert.match(trigger, /\n {2}push:\n {4}tags:\n {6}- "v\*"/);
  assert.doesNotMatch(trigger, /branches|pull_request|schedule|workflow_dispatch/);
  const permissions = workflow.slice(workflow.indexOf("\npermissions:"), workflow.indexOf("\nconcurrency:"));
  assert.equal(permissions.trim(), "permissions:\n  contents: write");
  for (const block of workflow.split(/\n\s+run: \|/).slice(1)) {
    const script = block.split(/\n\s+- (?:name|uses):/)[0];
    assert.doesNotMatch(script, /\$\{\{\s*(?:inputs|github\.event)\./, "event data must reach scripts through env");
  }
  assert.match(workflow, /node tools\/release\/version\.mjs --expect/);
  assert.match(workflow, /pnpm install --frozen-lockfile/);
  assert.ok(workflow.indexOf("pnpm check:windows-build") < workflow.indexOf("pnpm tauri:build:windows"));
  assert.match(workflow, /gh release create "\$env:RELEASE_TAG"[^\n]* --draft --verify-tag/);
  assert.doesNotMatch(workflow, /gh release (?:delete|edit|upload)|git push|--clobber|rhubarb/);
  assert.match(workflow, /- name: Show Tauri resource staging after a failure\n\s+if: failure\(\)/);
  assert.match(workflow, /Where-Object \{ \$_\.Name -match "\^\(CARGO\|RUST\)" \}/);
});

test("tauri-build stages resources beside the app with Cargo's newer build folder layout", () => {
  // Cargo 1.100 nests build-script output one level deeper; tauri-build before 2.7.0 then copies
  // bundle resources into target/<triple>/release/build, so the Windows release audit cannot find them.
  const lock = readFileSync(new URL("../src-tauri/Cargo.lock", import.meta.url), "utf8");
  const version = lock.match(/name = "tauri-build"\nversion = "(\d+)\.(\d+)\.(\d+)"/);
  assert.ok(version, "tauri-build is locked");
  const [major, minor] = version.slice(1, 3).map(Number);
  assert.ok(major > 2 || (major === 2 && minor >= 7), `tauri-build ${version.slice(1).join(".")} is older than 2.7.0`);
});

test("an in-place install replaces the bundled runtime folders before copying files", () => {
  // v26.11.24: an install over the earlier build kept _internal/websockets/speedups.pyd, which made
  // `import websockets` succeed as an empty namespace package and stopped the API at startup.
  const hooks = read("src-tauri/windows/installer-hooks.nsh");
  const preinstall = hooks.slice(hooks.indexOf("!macro NSIS_HOOK_PREINSTALL"), hooks.indexOf("!macroend", hooks.indexOf("!macro NSIS_HOOK_PREINSTALL")));
  const running = preinstall.indexOf('!insertmacro CheckIfAppIsRunning "${MAINBINARYNAME}.exe" "${PRODUCTNAME}"');
  for (const folder of ["scena-api-runtime", "environment-manager"]) {
    const removal = preinstall.indexOf(`RMDir /r "$INSTDIR\\${folder}"`);
    assert.ok(running >= 0 && removal > running, `${folder} is removed after the running-app check`);
    assert.ok(preinstall.includes(`${"$"}{FileExists} "$INSTDIR\\${folder}\\*.*"`), `${folder} removal failure stops the install`);
  }
  assert.match(preinstall, /Abort/);
});
