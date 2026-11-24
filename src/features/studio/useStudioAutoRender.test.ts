import { afterEach, describe, expect, it, vi } from "vitest";
import fixture from "../../../tests/fixtures/project-contract.json";
import type { StudioProject } from "../../types";
import { api } from "../../api";
import { ProjectEditSession } from "./projectEditSession";
import { useStudioAutoRender } from "./useStudioAutoRender";
import { createRenderJob, nextRenderSequence } from "./renderJobQueue";

function autoRenderModel(newTake = false) {
  const project = structuredClone(fixture) as StudioProject;
  const line = project.scenes[0].lines[0];
  const editSession = new ProjectEditSession(() => {});
  editSession.replace(project);
  editSession.persistence = {
    save: async (value) => {
      await api.saveProject(value);
      return true;
    },
    wait: async () => true,
    pause: () => {},
    resume: () => {},
    rebasePending: () => {},
  };
  return {
    editSession,
    autoGenerateEnabledRef: { current: true as boolean },
    autoGenerationRequestRef: { current: 0 },
    autoRenderQueue: { current: [createRenderJob(project, line, nextRenderSequence(), { mode: newTake ? "append" : "replace", cause: newTake ? "manual-new-take" : "line-edited", targetTakeId: newTake ? undefined : (line.selectedTakeId ?? undefined) }, editSession.capture().generation)] },
    autoRenderInProgress: { current: false as boolean },
    autoRenderActiveLineId: { current: null as string | null },
    playbackProtectedLineIds: { current: new Set<string>() },
    autoRenderPriorityActive: { current: false as boolean },
    autoRenderPriorityDepth: { current: 0 },
    processAutoRenderQueueRef: { current: async () => {} },
    runWithAutoRenderPriorityRef: { current: <T>(action: () => Promise<T>) => action() },
    reconcileAutoRenderQueueRef: { current: (_historyBaseRevision?: number) => {} },
    busyRef: { current: null },
    projectRef: { current: project },
    playingLineId: null,
    setBusy: vi.fn(),
    setNotice: vi.fn(),
    setStatusNotice: vi.fn(),
    setAutoGenerateEnabled: vi.fn(),
    stop: vi.fn(),
    applyGeneratedTake: vi.fn(),
  } satisfies Parameters<typeof useStudioAutoRender>[0];
}

function respond(model: ReturnType<typeof autoRenderModel>, status: number, detail: unknown) {
  const requests: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => {
      requests.push(path);
      if (path === "/api/project") return Response.json(model.projectRef.current);
      if (requests.filter((url) => url !== "/api/project").length === 1) {
        return Response.json({ detail }, { status });
      }
      return Response.json({ take: model.projectRef.current.scenes[0].lines[0].takes[0], projectRevision: model.projectRef.current.revision + 1 });
    }),
  );
  return requests;
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("passes a selected batch history group through queued new-take generation", async () => {
  const model = autoRenderModel(true);
  const job = model.autoRenderQueue.current[0];
  job.historyGroupId = crypto.randomUUID();
  const generate = vi.spyOn(api, "generateLine").mockResolvedValue({ take: model.projectRef.current.scenes[0].lines[0].takes[0], projectRevision: model.projectRef.current.revision + 1 });

  await useStudioAutoRender(model).processAutoRenderQueue();

  expect(generate).toHaveBeenCalledWith(job.lineId, model.projectRef.current.settings.quality, true, undefined, undefined, job.historyGroupId);
  // Start and completion are status notices, so they never reopen the dialog notice overlay.
  expect(model.setStatusNotice).toHaveBeenCalledWith("発話行の新しいテイクを生成しています…");
  expect(model.setNotice).not.toHaveBeenCalled();
});

it("rebases valid queued work on the restored edit session and revision", async () => {
  const model = autoRenderModel();
  const job = model.autoRenderQueue.current[0];
  job.historyBaseRevision = 0;
  model.autoGenerateEnabledRef.current = false;
  useStudioAutoRender(model);
  const restored = { ...model.projectRef.current, revision: 8 };
  model.editSession.restore(model.editSession.capture(), restored);
  model.projectRef.current = restored;
  model.reconcileAutoRenderQueueRef.current();
  expect(model.autoRenderQueue.current[0]).toMatchObject({ projectGeneration: model.editSession.capture().generation, historyBaseRevision: 8 });
  model.projectRef.current.scenes[0].lines[0].text = "changed";
  model.reconcileAutoRenderQueueRef.current();
  expect(model.autoRenderQueue.current).toEqual([]);
});

it("assigns a deletion history boundary to pending automatic work", () => {
  const model = autoRenderModel();
  const job = model.autoRenderQueue.current[0];
  expect(job.historyBaseRevision).toBeUndefined();
  useStudioAutoRender(model);
  const updated = { ...model.projectRef.current, revision: 9 };
  model.editSession.restore(model.editSession.capture(), updated);
  model.projectRef.current = updated;

  model.reconcileAutoRenderQueueRef.current(9);

  expect(model.autoRenderQueue.current[0]).toMatchObject({
    projectGeneration: model.editSession.capture().generation,
    historyBaseRevision: 9,
  });
});

it("keeps automatic work paused across nested history and batch priority actions", async () => {
  const model = autoRenderModel();
  model.autoGenerateEnabledRef.current = false;
  const actions = useStudioAutoRender(model);
  await actions.runWithAutoRenderPriority(async () => {
    await actions.runWithAutoRenderPriority(async () => {
      expect(model.autoRenderPriorityDepth.current).toBe(2);
    });
    expect(model.autoRenderPriorityActive.current).toBe(true);
    expect(model.autoRenderPriorityDepth.current).toBe(1);
  });
  expect(model.autoRenderPriorityActive.current).toBe(false);
  expect(model.autoRenderPriorityDepth.current).toBe(0);
});

it("allows a project edit while automatic generation is still running", async () => {
  const model = autoRenderModel();
  let finishRender: (value: Awaited<ReturnType<typeof api.regenerateLine>>) => void = () => {};
  const generate = vi.spyOn(api, "regenerateLine").mockImplementation(
    () =>
      new Promise((resolve) => {
        finishRender = resolve;
      }),
  );
  const render = useStudioAutoRender(model).processAutoRenderQueue();
  await vi.waitFor(() => expect(generate).toHaveBeenCalledOnce());

  const edit = vi.fn(async () => model.projectRef.current);
  const updated = await model.editSession.requestProject(edit);
  expect(updated).toBe(model.projectRef.current);
  expect(edit).toHaveBeenCalledOnce();
  expect(model.autoRenderInProgress.current).toBe(true);

  finishRender({ take: model.projectRef.current.scenes[0].lines[0].takes[0], projectRevision: 1 });
  await render;
});

it("drops an obsolete job before synthesis when settings change during persistence wait", async () => {
  const model = autoRenderModel();
  let finishSave: (value: boolean) => void = () => {};
  model.editSession.persistence!.wait = () =>
    new Promise((resolve) => {
      finishSave = resolve;
    });
  const regenerate = vi.spyOn(api, "regenerateLine");
  const running = useStudioAutoRender(model).processAutoRenderQueue();
  model.projectRef.current.scenes[0].lines[0].speechRate = 1.3;
  finishSave(true);
  await running;
  expect(regenerate).not.toHaveBeenCalled();
  expect(model.applyGeneratedTake).not.toHaveBeenCalled();
});

it("does not start synthesis after automatic generation is turned off during persistence wait", async () => {
  const model = autoRenderModel();
  let finishSave: (value: boolean) => void = () => {};
  model.editSession.persistence!.wait = () =>
    new Promise((resolve) => {
      finishSave = resolve;
    });
  const regenerate = vi.spyOn(api, "regenerateLine");
  const running = useStudioAutoRender(model).processAutoRenderQueue();
  model.autoGenerateEnabledRef.current = false;
  finishSave(true);
  await running;
  expect(regenerate).not.toHaveBeenCalled();
});

it("does not start synthesis while an undo priority action waits for an in-flight job", async () => {
  const model = autoRenderModel();
  let finishSave: (value: boolean) => void = () => {};
  model.editSession.persistence!.wait = () =>
    new Promise((resolve) => {
      finishSave = resolve;
    });
  const regenerate = vi.spyOn(api, "regenerateLine");
  const cancel = vi.spyOn(api, "cancelAutoRender").mockResolvedValue({ cancelled: false });
  const actions = useStudioAutoRender(model);
  const running = actions.processAutoRenderQueue();
  const restore = vi.fn(async () => {});
  const undo = actions.runWithAutoRenderPriority(restore);

  finishSave(true);
  await Promise.all([running, undo]);
  expect(cancel).toHaveBeenCalledOnce();
  expect(regenerate).not.toHaveBeenCalled();
  expect(restore).toHaveBeenCalledOnce();
});

describe("automatic generation through the API error boundary", () => {
  it("cancels an active automatic render only for the priority action and then resumes the queue", async () => {
    vi.useFakeTimers();
    const model = autoRenderModel();
    model.autoRenderInProgress.current = true;
    model.autoRenderQueue.current = [];
    const events: string[] = [];
    vi.spyOn(api, "cancelAutoRender").mockImplementation(async () => {
      events.push("cancel");
      model.autoRenderInProgress.current = false;
      return { cancelled: true };
    });
    const actions = useStudioAutoRender(model);
    await actions.runWithAutoRenderPriority(async () => {
      events.push("overlap");
    });
    expect(events).toEqual(["cancel", "overlap"]);
    expect(model.autoRenderPriorityActive.current).toBe(false);
  });

  it.each([false, true])("requeues a priority interruption once with newTake=%s", async (newTake) => {
    vi.useFakeTimers();
    vi.spyOn(console, "error").mockImplementation(() => {});
    const model = autoRenderModel(newTake);
    const requests = respond(model, 409, { code: "priority_interruption", message: "優先再生のため自動生成を中断しました。" });
    const actions = useStudioAutoRender(model);
    await actions.processAutoRenderQueue();
    expect(model.autoRenderQueue.current).toHaveLength(1);
    expect(model.autoRenderQueue.current[0].interruptionCount).toBe(1);
    await actions.processAutoRenderQueue();
    await vi.runAllTimersAsync();
    const generation = requests.filter((url) => url !== "/api/project");
    expect(generation).toHaveLength(2);
    expect(generation[0]).toBe(generation[1]);
    expect(generation[1]).toMatch(newTake ? /\/generate$/ : /\/regenerate$/);
    expect(model.applyGeneratedTake).toHaveBeenCalledOnce();
    expect(model.autoRenderQueue.current).toEqual([]);
  });

  it.each([
    [409, "競合しました。", true],
    [422, { code: "tts_model_unsupported_voice_design", message: "未対応" }, true],
  ])("drops a failed item without disabling automatic generation for status=%s when enabled=%s", async (status, detail, enabled) => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const model = autoRenderModel();
    respond(model, status as number, detail);
    const actions = useStudioAutoRender(model);
    const pending = actions.processAutoRenderQueue();
    model.autoGenerateEnabledRef.current = Boolean(enabled);
    await pending;
    expect(model.autoGenerateEnabledRef.current).toBe(Boolean(enabled));
    expect(model.setAutoGenerateEnabled).not.toHaveBeenCalled();
    expect(model.autoRenderQueue.current).toEqual([]);
    expect(model.setNotice).toHaveBeenLastCalledWith(expect.stringContaining("この生成要求を完了できませんでした:"));
  });

  it("does not PUT the whole project and resumes from the failed row", async () => {
    vi.useFakeTimers();
    vi.spyOn(console, "error").mockImplementation(() => {});
    const model = autoRenderModel();
    const remaining = "line-remaining";
    model.projectRef.current.scenes[0].lines.push({ ...structuredClone(model.projectRef.current.scenes[0].lines[0]), id: remaining });
    const remainingLine = model.projectRef.current.scenes[0].lines.find((line) => line.id === remaining)!;
    model.autoRenderQueue.current.push(createRenderJob(model.projectRef.current, remainingLine, nextRenderSequence(), { mode: "replace", cause: "line-edited", targetTakeId: remainingLine.selectedTakeId ?? undefined }, model.editSession.capture().generation));
    const requests = respond(model, 409, { code: "render_input_changed", message: "生成中に発話の内容が変更されました。" });
    const actions = useStudioAutoRender(model);

    await actions.processAutoRenderQueue();
    expect(model.autoRenderQueue.current.map((job) => job.lineId)).toEqual([remaining]);
    expect(requests).not.toContain("/api/project");

    model.autoGenerateEnabledRef.current = true;
    await actions.processAutoRenderQueue();
    await vi.runAllTimersAsync();
    expect(model.autoRenderQueue.current).toEqual([]);
    expect(requests.filter((url) => /\/(generate|regenerate)$/.test(url))).toHaveLength(2);
  });

  it("stops before TTS and keeps the concrete save failure reason", async () => {
    const model = autoRenderModel();
    model.editSession.persistence!.wait = async () => false;
    model.editSession.persistence!.failureReason = () => "プロジェクトを保存する空き容量がありません。";
    const generate = vi.spyOn(api, "regenerateLine");
    const actions = useStudioAutoRender(model);

    await actions.processAutoRenderQueue();

    expect(generate).not.toHaveBeenCalled();
    expect(model.autoGenerateEnabledRef.current).toBe(true);
    expect(model.autoRenderQueue.current).toEqual([]);
    expect(model.setNotice).toHaveBeenLastCalledWith("この生成要求を完了できませんでした: プロジェクトを保存する空き容量がありません。");
  });

  it("keeps protected-line jobs queued while executing an unprotected job", async () => {
    const model = autoRenderModel();
    const first = model.projectRef.current.scenes[0].lines[0];
    const second = { ...structuredClone(first), id: "line-outside-window" };
    model.projectRef.current.scenes[0].lines.push(second);
    const generation = model.editSession.capture().generation;
    model.autoRenderQueue.current = [
      createRenderJob(model.projectRef.current, first, nextRenderSequence(), { mode: "replace", cause: "line-edited", targetTakeId: first.selectedTakeId ?? undefined }, generation),
      createRenderJob(model.projectRef.current, second, nextRenderSequence(), { mode: "replace", cause: "line-edited", targetTakeId: second.selectedTakeId ?? undefined }, generation),
    ];
    model.playbackProtectedLineIds.current.add(first.id);
    const regenerate = vi.spyOn(api, "regenerateLine").mockResolvedValue({ take: second.takes[0], projectRevision: model.projectRef.current.revision + 1 });
    vi.spyOn(api, "saveProject").mockResolvedValue(model.projectRef.current);

    await useStudioAutoRender(model).processAutoRenderQueue();

    expect(regenerate).toHaveBeenCalledWith(second.id, model.projectRef.current.settings.quality, true, second.selectedTakeId, undefined);
    expect(model.autoRenderQueue.current.map((job) => job.lineId)).toEqual([first.id]);
  });

  it("skips a stale playback-missing job instead of appending Take 2 and regenerates the actually empty earlier line", async () => {
    const model = autoRenderModel();
    const first = model.projectRef.current.scenes[0].lines[0];
    const second = { ...structuredClone(first), id: "line-2" };
    model.projectRef.current.scenes[0].lines = [first, second];
    first.takes = [];
    first.selectedTakeId = null;
    const generation = model.editSession.capture().generation;
    const staleSecond = createRenderJob(model.projectRef.current, { ...second, takes: [], selectedTakeId: null }, nextRenderSequence(), { mode: "append", cause: "playback-required" }, generation);
    const deletedFirst = createRenderJob(model.projectRef.current, first, nextRenderSequence(), { mode: "append", cause: "last-take-deleted" }, generation);
    model.autoRenderQueue.current = [staleSecond, deletedFirst];
    const generate = vi.spyOn(api, "generateLine").mockResolvedValue({ take: { ...second.takes[0], id: "regenerated-first" }, projectRevision: model.projectRef.current.revision + 1 });

    await useStudioAutoRender(model).processAutoRenderQueue();
    await vi.waitFor(() => expect(generate).toHaveBeenCalledOnce());

    expect(generate).toHaveBeenCalledWith(first.id, model.projectRef.current.settings.quality, true, undefined, undefined);
    expect(model.autoRenderQueue.current).toEqual([]);
  });
});
