import { describe, expect, it, vi } from "vitest";
import { handleFileRequest } from "./useStudioFileDrop";

function model(overrides: Record<string, unknown> = {}) {
  return {
    setNotice: vi.fn(),
    busyRef: { current: null },
    autoRenderInProgress: { current: false },
    selectedLineGenerationActive: false,
    exportJob: null,
    stopAutoGeneration: vi.fn(),
    cancelSelectedLineGeneration: vi.fn(),
    cancelExport: vi.fn(),
    openWorkspace: vi.fn(),
    prepareCastImport: vi.fn(),
    ...overrides,
  };
}

describe("handleFileRequest", () => {
  it("routes projects and cast batches through the existing workflows", async () => {
    const target = model();
    await handleFileRequest(target as never, { kind: "project", path: "/tmp/作品.scena", unsupported: 0 });
    await handleFileRequest(target as never, { kind: "casts", paths: ["一.scenacast", "二.scenacast"], unsupported: 0 });
    expect(target.openWorkspace).toHaveBeenCalledWith(false, "/tmp/作品.scena");
    expect(target.prepareCastImport).toHaveBeenCalledWith(["一.scenacast", "二.scenacast"]);
  });

  it("rejects mixed requests before changing the project", async () => {
    const target = model();
    await handleFileRequest(target as never, { kind: "invalid", reason: "プロジェクトとキャストは分けてドロップしてください。", unsupported: 0 });
    expect(target.setNotice).toHaveBeenCalledWith("プロジェクトとキャストは分けてドロップしてください。");
    expect(target.openWorkspace).not.toHaveBeenCalled();
  });

  it("stops cancellable generation before opening a file", async () => {
    const busyRef = { current: "line-id" as string | null };
    const cancelSelectedLineGeneration = vi.fn(async () => {
      busyRef.current = null;
    });
    const target = model({ busyRef, selectedLineGenerationActive: true, cancelSelectedLineGeneration });
    await handleFileRequest(target as never, { kind: "project", path: "next.scena", unsupported: 0 });
    expect(cancelSelectedLineGeneration).toHaveBeenCalledOnce();
    expect(target.openWorkspace).toHaveBeenCalledWith(false, "next.scena");
  });
});
