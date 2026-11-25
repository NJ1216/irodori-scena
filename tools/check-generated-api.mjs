import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import process from "node:process";
import { spawnSync } from "node:child_process";
import { pnpmInvocation } from "./windows-build-contract.mjs";

const root = path.resolve(import.meta.dirname, "..");
const temporary = await mkdtemp(path.join(tmpdir(), "scena-openapi-"));
const schema = path.join(temporary, "openapi.json");
const types = path.join(temporary, "openapi.ts");
const hash = path.join(temporary, "api-schema-hash.ts");
try {
  const environment = { ...process.env, UV_CACHE_DIR: path.join(root, ".uv-cache") };
  const schemaResult = spawnSync("uv", ["run", "python", "tools/generate-openapi-fixture.py", schema, hash], {
    cwd: root,
    env: environment,
    encoding: "utf8",
  });
  if (schemaResult.status !== 0) throw new Error(schemaResult.stderr || schemaResult.stdout);
  const typeArguments = ["exec", "openapi-typescript", schema, "-o", types];
  const [packageManager, packageArguments] = process.platform === "win32" && process.env.npm_execpath ? pnpmInvocation(process.env.npm_execpath, typeArguments) : ["pnpm", typeArguments];
  const typeResult = spawnSync(packageManager, packageArguments, {
    cwd: root,
    encoding: "utf8",
  });
  if (typeResult.status !== 0) throw new Error(typeResult.stderr || typeResult.stdout);
  const pairs = [
    [schema, path.join(root, "tests/fixtures/openapi.json")],
    [types, path.join(root, "src/generated/openapi.ts")],
    [hash, path.join(root, "src/generated/api-schema-hash.ts")],
  ];
  for (const [generated, committed] of pairs) {
    if ((await readFile(generated, "utf8")) !== (await readFile(committed, "utf8"))) {
      throw new Error(`${path.relative(root, committed)} is stale; run pnpm generate:api`);
    }
  }
  console.log("Generated OpenAPI schema and TypeScript types are current.");
} finally {
  await rm(temporary, { recursive: true, force: true });
}
