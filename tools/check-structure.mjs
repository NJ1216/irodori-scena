import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const roots = ["src", "server", "tests", "tools"];
const extensions = new Set([".css", ".js", ".jsx", ".mjs", ".py", ".ts", ".tsx"]);
const defaultMaxLines = 500;
// Formatted stylesheets are one declaration per line, so their length says little about responsibility;
// they are reviewed for duplication and dead rules instead of being split by line count.
const lineLimitExemptExtensions = new Set([".css"]);
const defaultMaxFunctionNodes = 3_000;
const exceptionConfig = JSON.parse(await readFile(path.join(projectRoot, "structure-exceptions.json"), "utf8"));
const fileExceptions = exceptionConfig.files ?? exceptionConfig;
const typescriptExceptions = exceptionConfig.typescriptFiles ?? {};

async function sourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(
    entries.map(async (entry) => {
      const absolute = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        return sourceFiles(absolute);
      }
      return extensions.has(path.extname(entry.name)) ? [absolute] : [];
    }),
  );
  return nested.flat();
}

const files = (await Promise.all(roots.map((root) => sourceFiles(path.join(projectRoot, root))))).flat().filter((file) => !path.relative(projectRoot, file).startsWith(`src${path.sep}generated${path.sep}`));
const failures = [];
const legacyCompletionOwners = new Set(["server/modules/llm_client.py", "server/modules/llm_completion_service.py"]);

for (const file of files) {
  const relative = path.relative(projectRoot, file).split(path.sep).join("/");
  const content = await readFile(file, "utf8");
  const lines = content === "" ? 0 : content.split(/\r?\n/).length - Number(content.endsWith("\n"));
  const maximum = fileExceptions[relative]?.maxLines ?? defaultMaxLines;
  if (lines > maximum && !lineLimitExemptExtensions.has(path.extname(file))) {
    failures.push(`${relative}: ${lines} lines (maximum ${maximum})`);
  }
  if (/\.tsx?$/.test(relative)) {
    const source = ts.createSourceFile(relative, content, ts.ScriptTarget.Latest, true);
    const inspect = (node) => {
      if (ts.isFunctionLike(node) && node.body) {
        let nodes = 0;
        const count = (child) => {
          nodes += 1;
          ts.forEachChild(child, count);
        };
        count(node.body);
        if (nodes > defaultMaxFunctionNodes) {
          const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
          failures.push(`${relative}:${line}: function has ${nodes} AST nodes (maximum ${defaultMaxFunctionNodes})`);
        }
      }
      ts.forEachChild(node, inspect);
    };
    inspect(source);
  }
  if (relative.startsWith("server/") && !legacyCompletionOwners.has(relative) && /\b(?:openai_json_completion|openai_text_completion|openai_stream_text_completion)\s*\(/.test(content)) {
    failures.push(`${relative}: legacy completion API may only be used by LLM transport/service adapters`);
  }
}

for (const [relative, exception] of Object.entries(fileExceptions)) {
  if (!exception.reason || !exception.reviewWhen || !Number.isInteger(exception.maxLines)) {
    failures.push(`${relative}: exception needs maxLines, reason, and reviewWhen`);
  }
}

for (const [relative, exception] of Object.entries(typescriptExceptions)) {
  if (!exception.reason || !exception.reviewWhen || !Number.isInteger(exception.maxFunctionLines) || !Number.isInteger(exception.maxComplexity)) {
    failures.push(`${relative}: TypeScript exception needs numeric limits, reason, and reviewWhen`);
  }
  if (!files.some((file) => path.relative(projectRoot, file).split(path.sep).join("/") === relative)) {
    failures.push(`${relative}: TypeScript exception target does not exist`);
  }
}

if (failures.length > 0) {
  console.error(`Structure validation failed:\n${failures.join("\n")}`);
  process.exitCode = 1;
} else {
  console.log(`Structure validation passed for ${files.length} handwritten source files.`);
}
