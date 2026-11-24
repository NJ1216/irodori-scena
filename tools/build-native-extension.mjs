import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { copyWindowsNativeModule } from "./native-extension-output.mjs";

const root = fileURLToPath(new URL("../", import.meta.url));
function run(command, args, options = {}) {
  const result = spawnSync(command, args, { cwd: root, stdio: "inherit", ...options });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${command} failed (${result.status})`);
  return result;
}
if (process.platform !== "win32") {
  run("bash", ["tools/build-native-extension.sh"]);
} else {
  const python = process.env.SCENA_BUILD_PYTHON ?? run("uv", ["run", "python", "-c", "import sys; print(sys.executable)"], { encoding: "utf8", stdio: ["ignore", "pipe", "inherit"] }).stdout.trim();
  run("cargo", ["build", "--manifest-path", "native/scena-native/Cargo.toml", "--release"], { env: { ...process.env, PYO3_PYTHON: python } });
  const target = process.env.CARGO_TARGET_DIR ?? join(root, "native/scena-native/target");
  const outputDirectory = process.env.SCENA_NATIVE_MODULE_DIR ?? root;
  const modulePath = copyWindowsNativeModule(join(target, "release/scena_native.dll"), outputDirectory);
  run(python, ["-c", "import pathlib, scena_native, sys; assert pathlib.Path(scena_native.__file__).resolve() == pathlib.Path(sys.argv[1]).resolve(); assert callable(scena_native.mix_pcm_members_wav); assert callable(scena_native.render_overlap_wav); assert callable(scena_native.render_timeline_wav)", modulePath], {
    cwd: outputDirectory,
  });
}
