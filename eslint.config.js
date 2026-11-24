import js from "@eslint/js";
import { readFileSync } from "node:fs";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import sonarjs from "eslint-plugin-sonarjs";
import tseslint from "typescript-eslint";

const structureExceptions = JSON.parse(readFileSync(new URL("./structure-exceptions.json", import.meta.url), "utf8"));
const typescriptFunctionExceptions = Object.entries(structureExceptions.typescriptFiles ?? {}).map(([file, exception]) => ({
  files: [file],
  rules: {
    complexity: ["error", exception.maxComplexity],
    "max-lines-per-function": [
      "error",
      {
        max: exception.maxFunctionLines,
        skipBlankLines: true,
        skipComments: true,
        IIFEs: true,
      },
    ],
  },
}));

export default tseslint.config(
  {
    ignores: ["artifacts/**", "build/**", "coverage/**", "dist/**", "src/generated/**", "node_modules/**", "playwright-report/**", ".playwright-cli/**", "scena-data/**", "src-tauri/target/**", "src-tauri/resources/omlx-runtime/**", "test-results/**", "userproject/**", ".venv/**", ".uv-cache/**", "*.spec"],
  },
  {
    ...js.configs.recommended,
    files: ["**/*.{js,cjs,mjs}"],
    languageOptions: {
      globals: globals.node,
    },
  },
  ...tseslint.configs.recommended,
  {
    files: ["**/*.cjs"],
    rules: { "@typescript-eslint/no-require-imports": "off" },
  },
  {
    files: ["tools/lipsync_version_mouth_review.js"],
    languageOptions: { globals: { ...globals.browser, records: "readonly" } },
  },
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
      sonarjs,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      complexity: ["error", 15],
      "sonarjs/cognitive-complexity": ["error", 30],
      "max-len": ["error", { code: 320, ignoreComments: true, ignoreStrings: true, ignoreTemplateLiterals: true, ignoreUrls: true }],
      "max-lines-per-function": ["error", { max: 120, skipBlankLines: true, skipComments: true, IIFEs: true }],
    },
  },
  ...typescriptFunctionExceptions,
);
