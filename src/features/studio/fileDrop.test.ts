import { describe, expect, it } from "vitest";
import { classifyDroppedPaths } from "./fileDrop";

describe("classifyDroppedPaths", () => {
  it("accepts one project case-insensitively and counts unrelated files", () => {
    expect(classifyDroppedPaths(["/tmp/作品.SCENA", "/tmp/readme.txt"])).toEqual({ kind: "project", path: "/tmp/作品.SCENA", unsupported: 1 });
  });
  it("accepts multiple cast files", () => {
    expect(classifyDroppedPaths(["a.scenacast", "B.SCENACAST"])).toEqual({ kind: "casts", paths: ["a.scenacast", "B.SCENACAST"], unsupported: 0 });
  });
  it("rejects mixed inputs and multiple projects", () => {
    expect(classifyDroppedPaths(["a.scena", "b.scenacast"]).kind).toBe("invalid");
    expect(classifyDroppedPaths(["a.scena", "b.SCENA"]).kind).toBe("invalid");
  });
  it("rejects a drop with no supported files", () => {
    expect(classifyDroppedPaths(["readme.txt"])).toMatchObject({ kind: "invalid", unsupported: 1 });
  });
});
