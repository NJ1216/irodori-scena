import { readFile, readdir, stat } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dist = path.join(root, "dist");
const html = await readFile(path.join(dist, "index.html"), "utf8");
const entryMatch = html.match(/<script[^>]+src="[^"]*\/assets\/([^"]+\.js)"/);
if (!entryMatch) throw new Error("Built index.html has no JavaScript entry.");

const entryLimit = 500_000;
const chunkLimit = 300_000;
const failures = [];
for (const name of await readdir(path.join(dist, "assets"))) {
  if (!name.endsWith(".js")) continue;
  const bytes = (await stat(path.join(dist, "assets", name))).size;
  const limit = name === entryMatch[1] ? entryLimit : chunkLimit;
  if (bytes >= limit) failures.push(`${name}: ${bytes} bytes (budget < ${limit})`);
}
if (failures.length) {
  console.error(`Bundle budget failed:\n${failures.join("\n")}`);
  process.exitCode = 1;
} else {
  console.log("Bundle budget passed: entry <500 kB and every async JavaScript chunk <300 kB.");
}
