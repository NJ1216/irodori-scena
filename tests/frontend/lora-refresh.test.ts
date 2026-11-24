import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";
import { transformWithOxc } from "vite";

const feature = "src/features/lora/";
async function transform(filename: string, source?: string) {
  return (await transformWithOxc(source ?? (await readFile(filename, "utf8")), filename, { jsx: { runtime: "automatic", development: true, refresh: true } })).code;
}
function signature(code: string, name: string) {
  const match = code.match(new RegExp(`_s\\(${name}, "([^"]+)"`));
  expect(match, `${name} must have a DEV Fast Refresh hook signature`).not.toBeNull();
  return match?.[1];
}

describe("LoRA custom-hook DEV refresh", () => {
  it("tracks nested hook signatures and detects a changed hook order", async () => {
    const filename = `${feature}loraDeletionHook.tsx`;
    const source = await readFile(filename, "utf8");
    const original = await transform(filename, source);
    const edited = await transform(filename, source.replace('const [errorKey, setErrorKey] = useState("");', 'const [errorKey, setErrorKey] = useState("");\nuseRef(null);'));
    expect(signature(edited, "useLoraDeletion")).not.toBe(signature(original, "useLoraDeletion"));
    expect(original).toMatch(/return \[useDestructiveConfirmation, useLoraDialogAction\]/);
    signature(await transform(`${feature}loraDialogActionHook.tsx`), "useLoraDialogAction");
    const parent = await transform(`${feature}LoraLibraryPanel.tsx`);
    signature(parent, "LoraLibraryPanel");
    expect(parent).toMatch(/return \[useLoraDeletion\]/);
  });
});
