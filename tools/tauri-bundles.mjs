import { existsSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

// Values of a CLI option: "--bundles app,dmg", "--bundles app dmg" or "--bundles=dmg".
function optionValues(args, names) {
  const values = [];
  args.forEach((arg, index) => {
    const [name, inline] = arg.split("=", 2);
    if (!names.includes(name)) return;
    if (inline !== undefined) values.push(inline);
    else for (let i = index + 1; i < args.length && !args[i].startsWith("-"); i += 1) values.push(args[i]);
  });
  return values.flatMap((value) => value.split(",")).filter(Boolean);
}

/**
 * After a successful macOS `tauri build`, keep only the DMG of the current version:
 * remove the intermediate .app bundle and DMGs of other versions. A build that asks
 * for the app bundle explicitly (`--bundles app,...`, as the release check does)
 * keeps it. Returns the removed paths.
 */
export function tidyMacBundles(root, args) {
  if (args[0] !== "build" || args.includes("--no-bundle")) return [];
  if (optionValues(args, ["--bundles", "-b"]).includes("app")) return [];
  const { productName, version } = JSON.parse(readFileSync(join(root, "src-tauri/tauri.conf.json"), "utf8"));
  const [target] = optionValues(args, ["--target", "-t"]);
  const profile = args.includes("--debug") || args.includes("-d") ? "debug" : "release";
  const bundle = join(root, "src-tauri/target", ...(target ? [target] : []), profile, "bundle");
  const dmgDir = join(bundle, "dmg");
  if (!existsSync(dmgDir)) return [];
  const current = `${productName}_${version}_`;
  const dmgs = readdirSync(dmgDir).filter((name) => name.startsWith(`${productName}_`) && name.endsWith(".dmg"));
  // Without a DMG of this version the .app is the only result; leave everything.
  if (!dmgs.some((name) => name.startsWith(current))) return [];
  const removed = [join(bundle, "macos", `${productName}.app`)].filter((path) => existsSync(path));
  removed.push(...dmgs.filter((name) => !name.startsWith(current)).map((name) => join(dmgDir, name)));
  for (const path of removed) rmSync(path, { recursive: true, force: true });
  return removed;
}

// `node tools/tauri-bundles.mjs build --target <triple>` runs after the macOS build and its bundle inspection.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const root = fileURLToPath(new URL("../", import.meta.url));
  for (const path of tidyMacBundles(root, process.argv.slice(2))) console.log(`Removed ${path.slice(root.length)}`);
}
