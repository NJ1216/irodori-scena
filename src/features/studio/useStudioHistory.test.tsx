// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { HISTORY_APPLIED_EVENT, HISTORY_CHANGED_EVENT } from "../../api";
import fixture from "../../../tests/fixtures/project-contract.json";
import type { StudioProject } from "../../types";
import { ProjectEditSession } from "./projectEditSession";
import { useStudioHistory } from "./useStudioHistory";

const mocks = vi.hoisted(() => ({ historyStatus: vi.fn(), changeHistory: vi.fn(), project: vi.fn() }));

vi.mock("../../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api")>()),
  api: { historyStatus: mocks.historyStatus, changeHistory: mocks.changeHistory, project: mocks.project },
}));

beforeEach(() => {
  mocks.historyStatus.mockReset().mockResolvedValue({ canUndo: false, canRedo: false, busy: false });
  mocks.changeHistory.mockReset().mockResolvedValue({ canUndo: false, canRedo: true, busy: false });
  mocks.project.mockReset().mockResolvedValue({ id: "project-1" });
});

describe("useStudioHistory", () => {
  it("restores an unused cast during automatic generation without losing an existing take", async () => {
    const project = structuredClone(fixture) as StudioProject;
    const restored = { ...project, characters: [...project.characters, { ...project.characters[0], id: "unused" }] };
    const session = new ProjectEditSession(() => {});
    session.replace(project);
    mocks.project.mockResolvedValueOnce(restored).mockResolvedValueOnce(project);
    const model = {
      tab: "characters" as const,
      busy: project.scenes[0].lines[0].id,
      editSession: session,
      setNotice: vi.fn(),
      autoRenderInProgress: { current: true },
      autoRenderActiveLineId: { current: project.scenes[0].lines[0].id },
      runWithAutoRenderPriorityRef: { current: async <T,>(action: () => Promise<T>) => action() },
    } satisfies Parameters<typeof useStudioHistory>[0];
    const { result, unmount } = renderHook(() => useStudioHistory(model));
    await act(async () => result.current.undo());
    expect(session.savedProject()?.characters.map((character) => character.id)).toContain("unused");
    expect(session.savedProject()?.scenes[0].lines[0].takes).toEqual(project.scenes[0].lines[0].takes);
    await act(async () => result.current.redo());
    expect(session.savedProject()?.characters.map((character) => character.id)).not.toContain("unused");
    expect(session.savedProject()?.scenes[0].lines[0].takes).toEqual(project.scenes[0].lines[0].takes);
    unmount();
  });
  it("loads only the active history scope and refreshes it after a matching mutation", async () => {
    const model = {
      tab: "script",
      busy: null,
      editSession: new ProjectEditSession(() => {}),
      setNotice: vi.fn(),
    } satisfies Parameters<typeof useStudioHistory>[0];
    renderHook(() => useStudioHistory(model));

    await act(async () => undefined);
    expect(mocks.historyStatus).toHaveBeenCalledTimes(1);
    expect(mocks.historyStatus).toHaveBeenLastCalledWith("script");

    await act(async () => {
      window.dispatchEvent(new CustomEvent(HISTORY_CHANGED_EVENT, { detail: "characters" }));
    });
    expect(mocks.historyStatus).toHaveBeenCalledTimes(1);

    await act(async () => {
      window.dispatchEvent(new CustomEvent(HISTORY_CHANGED_EVENT, { detail: "script" }));
    });
    expect(mocks.historyStatus).toHaveBeenCalledTimes(2);
  });

  it("announces a pronunciation restore after undo completes", async () => {
    const applied = vi.fn();
    window.addEventListener(HISTORY_APPLIED_EVENT, applied);
    const model = {
      tab: "pronunciation",
      busy: null,
      editSession: new ProjectEditSession(() => {}),
      setNotice: vi.fn(),
    } satisfies Parameters<typeof useStudioHistory>[0];
    const { result } = renderHook(() => useStudioHistory(model));
    await act(async () => result.current.undo());
    expect(applied).toHaveBeenCalledOnce();
    expect((applied.mock.calls[0]?.[0] as CustomEvent).detail).toBe("pronunciation");
    window.removeEventListener(HISTORY_APPLIED_EVENT, applied);
  });

  it("interrupts automatic generation before undo and enables the history action while it runs", async () => {
    mocks.historyStatus.mockResolvedValue({ canUndo: true, canRedo: false, busy: false });
    let finishCancellation!: () => void;
    const cancellation = new Promise<void>((resolve) => {
      finishCancellation = resolve;
    });
    const events: string[] = [];
    mocks.changeHistory.mockImplementation(async () => {
      events.push("undo");
      return { canUndo: false, canRedo: true, busy: false };
    });
    const model = {
      tab: "script",
      busy: "line-1",
      editSession: new ProjectEditSession(() => {}),
      setNotice: vi.fn(),
      autoRenderInProgress: { current: true },
      autoRenderActiveLineId: { current: "line-1" },
      runWithAutoRenderPriorityRef: {
        current: async <T,>(action: () => Promise<T>) => {
          events.push("cancel");
          await cancellation;
          events.push("stopped");
          return action();
        },
      },
    } satisfies Parameters<typeof useStudioHistory>[0];
    const { result } = renderHook(() => useStudioHistory(model));
    await act(async () => undefined);
    expect(result.current.historyStatus).toMatchObject({ canUndo: true, busy: false });

    let undo!: Promise<void>;
    act(() => {
      undo = result.current.undo();
    });
    expect(result.current.historyStatus.busy).toBe(true);
    expect(events).toEqual(["cancel"]);
    expect(mocks.changeHistory).not.toHaveBeenCalled();
    await act(async () => {
      finishCancellation();
      await undo;
    });
    expect(events).toEqual(["cancel", "stopped", "undo"]);
  });
});

describe("selected generation history", () => {
  it.each(["characters", "pronunciation"] as const)("pauses selected generation for %s history and resumes after restoration", async (tab) => {
    const events: string[] = [];
    const model = {
      tab,
      busy: "generate-selected-lines",
      editSession: new ProjectEditSession(() => {}),
      setNotice: vi.fn(),
      selectedLineGenerationActive: true,
      selectedLineGenerationPauseRef: {
        current: vi.fn(async () => {
          events.push("pause");
          return async () => {
            events.push("resume");
          };
        }),
      },
      runWithAutoRenderPriorityRef: {
        current: async <T,>(action: () => Promise<T>) => {
          events.push("priority");
          return action();
        },
      },
      reconcileAutoRenderQueueRef: { current: () => events.push("reconcile") },
    } satisfies Parameters<typeof useStudioHistory>[0];
    mocks.changeHistory.mockImplementation(async () => {
      events.push("restore");
      return { canUndo: false, canRedo: true, busy: false };
    });
    const { result } = renderHook(() => useStudioHistory(model));
    await act(async () => result.current.undo());
    expect(events).toEqual(["priority", "pause", "restore", "reconcile", "resume"]);
  });

  it("resumes a paused batch even when history restoration fails", async () => {
    const resume = vi.fn(async () => {});
    mocks.changeHistory.mockRejectedValueOnce(new Error("restore failed"));
    const model = {
      tab: "characters" as const,
      busy: "generate-selected-lines",
      editSession: new ProjectEditSession(() => {}),
      setNotice: vi.fn(),
      selectedLineGenerationActive: true,
      selectedLineGenerationPauseRef: { current: vi.fn(async () => resume) },
    } satisfies Parameters<typeof useStudioHistory>[0];
    const { result } = renderHook(() => useStudioHistory(model));
    await act(async () => result.current.undo());
    expect(resume).toHaveBeenCalledOnce();
    expect(model.setNotice).toHaveBeenCalledWith("履歴を復元できません: restore failed");
  });
  it("stops a selected-line batch before undo even when no completed history is visible yet", async () => {
    const events: string[] = [];
    let finishCancellation!: () => void;
    const cancellation = new Promise<void>((resolve) => {
      finishCancellation = resolve;
    });
    mocks.changeHistory.mockImplementation(async () => {
      events.push("undo");
      return { canUndo: false, canRedo: true, busy: false };
    });
    const model = {
      tab: "script",
      busy: null,
      editSession: new ProjectEditSession(() => {}),
      setNotice: vi.fn(),
      selectedLineGenerationActive: true,
      selectedLineGenerationCancelRef: {
        current: vi.fn(async () => {
          events.push("cancel");
          await cancellation;
          events.push("stopped");
        }),
      },
      runWithAutoRenderPriorityRef: {
        current: async <T,>(action: () => Promise<T>) => {
          events.push("priority");
          return action();
        },
      },
    } satisfies Parameters<typeof useStudioHistory>[0];
    const { result } = renderHook(() => useStudioHistory(model));
    await act(async () => undefined);
    expect(result.current.historyStatus).toMatchObject({ canUndo: true, canRedo: false, busy: false });

    let undo!: Promise<void>;
    act(() => {
      undo = result.current.undo();
    });
    expect(events).toEqual(["priority", "cancel"]);
    expect(mocks.changeHistory).not.toHaveBeenCalled();
    await act(async () => {
      finishCancellation();
      await undo;
    });
    expect(events).toEqual(["priority", "cancel", "stopped", "undo"]);
  });
});
