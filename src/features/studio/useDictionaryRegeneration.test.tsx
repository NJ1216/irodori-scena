// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { StudioProject } from "../../types";
import { ProjectEditSession } from "./projectEditSession";
import { useDictionaryRegeneration } from "./useDictionaryRegeneration";
import { createRenderJob, nextRenderSequence } from "./renderJobQueue";

const mocks = vi.hoisted(() => ({ generateLine: vi.fn(), regenerateLine: vi.fn() }));
vi.mock("../../api", () => ({ api: { ...mocks, project: vi.fn() } }));

const take = { id: "take", audioUrl: "/take.wav", seed: 1, quality: "fast", stageDirection: "", createdAt: 1 } as const;
const project = {
  scenes: [
    {
      id: "scene",
      lines: ["line-1", "line-2", "line-3", "line-4"].map((id) => ({
        id,
        text: id,
        characterId: "cast",
        takes: [take],
        selectedTakeId: take.id,
      })),
    },
  ],
  settings: { quality: "fast" },
} as StudioProject;

describe("useDictionaryRegeneration", () => {
  it("merges affected cues without cancelling or directly generating during auto render", async () => {
    const process = vi.fn(async () => {});
    const stop = vi.fn();
    const model = {
      projectRef: { current: project },
      editSession: new ProjectEditSession(() => {}),
      setBusy: vi.fn(),
      setBatchGeneratingLineId: vi.fn(),
      setNotice: vi.fn(),
      setStatusNotice: vi.fn(),
      stop,
      autoGenerateEnabledRef: { current: true },
      autoRenderQueue: { current: [createRenderJob(project, project.scenes[0].lines[3], nextRenderSequence(), { mode: "append", cause: "dictionary" })] },
      processAutoRenderQueueRef: { current: process },
      applyGeneratedTake: vi.fn(),
    };
    const { result } = renderHook(() => useDictionaryRegeneration(model));

    await act(() => result.current(["line-1", "line-4"], "append"));

    expect(model.autoRenderQueue.current.map((job) => job.lineId)).toEqual(["line-1", "line-4"]);
    expect(process).toHaveBeenCalledOnce();
    expect(stop).not.toHaveBeenCalled();
    expect(mocks.generateLine).not.toHaveBeenCalled();
    expect(mocks.regenerateLine).not.toHaveBeenCalled();
  });
});
