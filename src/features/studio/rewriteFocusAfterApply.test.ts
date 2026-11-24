import { expect, it } from "vitest";
import type { StudioProject } from "../../types";
import { rewriteFocusAfterApply } from "./rewriteFocusAfterApply";

const project = (ids: string[]) => ({ scenes: [{ lines: ids.map((id) => ({ id })) }] }) as StudioProject;

it("keeps the focused line when rewrite preserves it", () => {
  expect(rewriteFocusAfterApply(project(["a", "b", "c"]), project(["a", "b", "c"]), ["b"], "c")).toBe("c");
});

it("focuses the replacement at the first rewritten position", () => {
  expect(rewriteFocusAfterApply(project(["a", "b", "c", "d"]), project(["a", "replacement", "d"]), ["b", "c"], "c")).toBe("replacement");
});

it("falls back to the final remaining line or null", () => {
  expect(rewriteFocusAfterApply(project(["a", "b"]), project(["a"]), ["b"], "b")).toBe("a");
  expect(rewriteFocusAfterApply(project(["a"]), project([]), ["a"], "a")).toBeNull();
});
