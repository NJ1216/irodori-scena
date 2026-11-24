import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { TAURI_DEV_CONFIG, TAURI_DEV_RUNNER, tauriInvocation } from "./tauri-command-core.mjs";

const readJson = (path) => JSON.parse(readFileSync(new URL(`../${path}`, import.meta.url), "utf8"));
const release = readJson("src-tauri/tauri.conf.json");
const releaseOverrides = readJson("src-tauri/tauri.release.conf.json");
const windowsRelease = readJson("src-tauri/tauri.windows.release.conf.json");
const dev = readJson(TAURI_DEV_CONFIG);

assert.equal(release.identifier, "com.irodori-scena");
// An identifier ending in ".app" names macOS folders that Finder shows as applications.
assert.ok(!release.identifier.endsWith(".app"));
assert.equal(release.app.windows[0].title, "irodori SCENA");
assert.deepEqual(release.bundle.fileAssociations, [
  {
    ext: ["scena"],
    name: "SCENA Project",
    description: "irodori SCENA プロジェクト",
    role: "Editor",
    rank: "Alternate",
    exportedType: { identifier: "com.irodori-scena.project", conformsTo: ["public.data"] },
  },
  {
    ext: ["scenacast"],
    name: "SCENA Cast",
    description: "irodori SCENA キャスト",
    role: "Viewer",
    rank: "Alternate",
    exportedType: { identifier: "com.irodori-scena.cast", conformsTo: ["public.data"] },
  },
]);
assert.equal(dev.identifier, "com.irodori-scena.dev");
assert.equal(dev.app.windows[0].title, "irodori SCENA [DEV]");
assert.notEqual(dev.identifier, release.identifier);
assert.notEqual(dev.app.windows[0].title, release.app.windows[0].title);
assert.equal(JSON.stringify(releaseOverrides).includes("com.irodori-scena.dev"), false);
assert.equal(JSON.stringify(releaseOverrides).includes("[DEV]"), false);
assert.deepEqual(windowsRelease.bundle.targets, ["nsis"]);
assert.equal(windowsRelease.bundle.windows.nsis.installMode, "both");
assert.deepEqual(windowsRelease.bundle.windows.nsis.languages, ["Japanese"]);
assert.equal(windowsRelease.bundle.windows.nsis.template, "windows/installer.nsi");
assert.equal(windowsRelease.bundle.windows.nsis.installerHooks, "windows/installer-hooks.nsh");
const installerHooks = readFileSync(new URL("../src-tauri/windows/installer-hooks.nsh", import.meta.url), "utf8");
const installerTemplate = readFileSync(new URL("../src-tauri/windows/installer.nsi", import.meta.url), "utf8");
const tauriRuntime = readFileSync(new URL("../src-tauri/src/lib.rs", import.meta.url), "utf8");
assert.match(installerHooks, /HKCU.*\$\{UNINSTKEY\}.*CurrentUser/);
assert.match(installerHooks, /\/S \/UPDATE/);
assert.match(installerHooks, /NSIS_HOOK_PREUNINSTALL/);
assert.match(installerHooks, /--cleanup-user-data/);
assert.match(installerHooks, /--error-log/);
assert.doesNotMatch(installerHooks, /--data-root|--webview-root|\$APPDATA|\$LOCALAPPDATA/);
assert.doesNotMatch(installerHooks, /com\.irodori-scena\.dev|scena-data/);
assert.match(installerHooks, /\$UpdateMode <> 1/);
assert.match(installerHooks, /NSIS_HOOK_POSTUNINSTALL/);
assert.match(installerHooks, /DeleteRegKey HKCU "\$\{MANUPRODUCTKEY\}"/);
assert.match(installerHooks, /DeleteRegKey HKLM "\$\{MANUPRODUCTKEY\}"/);
assert.match(installerHooks, /Delete \/REBOOTOK "\$INSTDIR\\uninstall\.exe"/);
assert.match(installerTemplate, /StrCpy \$DeleteManagedData 1/);
assert.match(installerTemplate, /StrCpy \$DeleteManagedData 0/);
assert.match(installerTemplate, /UninstPage custom un\.UninstallOptionsPage/);
assert.match(installerTemplate, /NSD_CreateRadioButton[^\n]*完全に削除/);
// An ordinary or silent uninstall keeps managed data; complete removal is an explicit choice (2026-11-25).
assert.match(installerTemplate, /Function un\.onInit\s+StrCpy \$DeleteManagedData 0/);
assert.ok(installerTemplate.indexOf("Pop $KeepManagedDataRadio") < installerTemplate.indexOf("Pop $DeleteManagedDataRadio"), "the keep-data choice is listed first");
assert.match(installerTemplate, /NSD_CreateRadioButton[^\n]*保持する（推奨）/);
assert.doesNotMatch(installerTemplate, /完全に削除する（推奨）/);
assert.match(installerTemplate, /\$UpdateMode = 1[\s\S]*Abort[\s\S]*NSD_CreateRadioButton/);
assert.ok(installerTemplate.indexOf('CheckIfAppIsRunning "${MAINBINARYNAME}.exe"') < installerTemplate.indexOf("NSIS_HOOK_PREUNINSTALL"), "the running app must be stopped before managed-data cleanup");
assert.ok(installerTemplate.indexOf("NSIS_HOOK_PREUNINSTALL") < installerTemplate.indexOf('Delete "$INSTDIR\\${MAINBINARYNAME}.exe"'), "the packaged cleanup CLI must run before installed resources are deleted");
assert.match(installerTemplate, /MULTIUSER_EXECUTIONLEVEL Highest/);
assert.match(installerTemplate, /MULTIUSER_INSTALLMODE_DEFAULT_REGISTRY_VALUENAME "CurrentUser"/);
assert.doesNotMatch(installerTemplate, /MULTIUSER_INSTALLMODE_DEFAULT_CURRENTUSER/);
assert.match(installerTemplate, /MULTIUSER_INSTALLMODE_INSTDIR "\$\{PRODUCTNAME\}"/);
assert.match(tauriRuntime, /const RELEASE_DATA_DIRECTORY: &str = "irodori-SCENA"/);
assert.equal(JSON.stringify(windowsRelease).includes("omlx"), false);
for (const key of ["width", "height", "minWidth", "minHeight", "visible"]) {
  assert.equal(dev.app.windows[0][key], release.app.windows[0][key]);
}

assert.deepEqual(tauriInvocation([], "darwin"), ["exec", "tauri", "dev", "--config", TAURI_DEV_CONFIG, "--runner", TAURI_DEV_RUNNER]);
assert.deepEqual(tauriInvocation(["dev", "--verbose"], "darwin"), ["exec", "tauri", "dev", "--config", TAURI_DEV_CONFIG, "--runner", TAURI_DEV_RUNNER, "--verbose"]);
assert.deepEqual(tauriInvocation(["build", "--debug"], "darwin"), ["run", "tauri:build:arm64", "--", "--debug"]);
assert.deepEqual(tauriInvocation(["build", "--debug"], "win32"), ["run", "tauri:build:windows", "--", "--debug"]);
assert.deepEqual(tauriInvocation(["dev"], "win32"), ["exec", "tauri", "dev", "--config", TAURI_DEV_CONFIG, "--config", "src-tauri/tauri.windows.conf.json", "--no-watch"]);
assert.deepEqual(tauriInvocation(["dev", "--no-watch"], "win32"), ["exec", "tauri", "dev", "--config", TAURI_DEV_CONFIG, "--config", "src-tauri/tauri.windows.conf.json", "--no-watch"]);
