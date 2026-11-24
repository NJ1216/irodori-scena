import { copyFileSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

export function copyWindowsNativeModule(source, outputDirectory) {
  mkdirSync(outputDirectory, { recursive: true });
  const destination = join(outputDirectory, "scena_native.pyd");
  copyFileSync(source, destination);
  return destination;
}

export function verifyBundledNativeModule(expected, bundled) {
  if (!readFileSync(expected).equals(readFileSync(bundled))) {
    throw new Error(`PyInstaller bundled a different native module: ${bundled}`);
  }
}
