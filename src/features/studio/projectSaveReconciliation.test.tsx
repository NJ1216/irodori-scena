import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import projectFixture from "../../../tests/fixtures/project-contract.json";
import { ApiError } from "../../api-error";
import type { StudioProject } from "../../types";
import { useProjectEditSession } from "./useProjectEditSession";

const mocks = vi.hoisted(() => ({ saveProject: vi.fn(), patchProjectMetadata: vi.fn(), patchProjectLine: vi.fn() }));
vi.mock("../../api", () => ({ api: mocks }));
const fixture = projectFixture as StudioProject;
const project = () => structuredClone(fixture) as StudioProject;
const line = (value: StudioProject) => value.scenes[0].lines[0];
function session() {
  const { result } = renderHook(() => useProjectEditSession(vi.fn()));
  act(() => result.current.editSession.replace(project()));
  return result;
}
beforeEach(() => {
  vi.resetAllMocks();
  mocks.patchProjectLine.mockResolvedValue({ revision: 1 });
  mocks.patchProjectMetadata.mockResolvedValue({ revision: 3 });
  mocks.saveProject.mockImplementation(async (snapshot: StudioProject) => ({ ...snapshot, revision: snapshot.revision + 1 }));
});

it("reflects the server's invalidated take after committing new text", async () => {
  const result = session();
  await act(async () => {
    result.current.editSession.updateLine(line(fixture).id, { text: "変更した台詞" });
    result.current.editSession.commitLine(line(fixture).id);
    expect(await result.current.editSession.save()).toBe(true);
  });
  expect(mocks.patchProjectLine).toHaveBeenCalledOnce();
  expect(line(result.current.project!).selectedTakeId).toBeNull();
  expect(line(result.current.project!).takes).toEqual(line(fixture).takes);
});

it("keeps an explicitly selected take when its character is saved in the same patch", async () => {
  const result = session();
  const original = project();
  const selected = { ...line(original).takes[0], id: "other-cast-take", characterId: "other-cast" };
  line(original).takes.push(selected);
  act(() => result.current.editSession.replace(original));
  await act(async () => {
    result.current.editSession.updateLine(line(original).id, { characterId: selected.characterId, selectedTakeId: selected.id });
    expect(await result.current.editSession.save()).toBe(true);
  });
  expect(mocks.patchProjectLine).toHaveBeenCalledExactlyOnceWith(line(original).id, 0, { characterId: selected.characterId, selectedTakeId: selected.id });
  expect(line(result.current.project!)).toMatchObject({ characterId: selected.characterId, selectedTakeId: selected.id });
  await act(async () => {
    result.current.editSession.update((p) => ({ ...p, title: "keep this take" }));
    expect(await result.current.editSession.save()).toBe(true);
  });
  expect(line(result.current.confirmedProject.current!).selectedTakeId).toBe(selected.id);
});

it.each(["speechRate", "gapSeconds"] as const)("persists clearing %s through JSON and retains it on the following save", async (key) => {
  const result = session();
  const original = project();
  line(original)[key] = 1.5;
  mocks.saveProject.mockImplementation(async (snapshot: StudioProject) => JSON.parse(JSON.stringify({ ...snapshot, revision: snapshot.revision + 1 })));
  act(() => result.current.editSession.replace(original));
  await act(async () => {
    result.current.editSession.updateLine(line(original).id, { [key]: undefined });
    expect(await result.current.editSession.save()).toBe(true);
  });
  expect(mocks.saveProject).toHaveBeenCalledOnce();
  expect(mocks.patchProjectLine).not.toHaveBeenCalled();
  expect(line(result.current.project!)[key]).toBeUndefined();
  await act(async () => {
    result.current.editSession.update((p) => ({ ...p, title: "after reset" }));
    expect(await result.current.editSession.save()).toBe(true);
  });
  expect(mocks.patchProjectMetadata).toHaveBeenCalledExactlyOnceWith(1, { title: "after reset" });
  expect(line(result.current.confirmedProject.current!)[key]).toBeUndefined();
});

it("keeps a concurrently generated take through conflict resolution and the following save", async () => {
  const remote = project();
  remote.revision = 1;
  line(remote).takes.push({ ...line(remote).takes[0], id: "server-new-take" });
  line(remote).selectedTakeId = "server-new-take";
  mocks.patchProjectMetadata.mockRejectedValueOnce(new ApiError("conflict", 409, { currentProject: remote }, "project_revision_conflict", "http"));
  const result = session();
  await act(async () => {
    result.current.editSession.update((p) => ({ ...p, title: "first edit" }));
    expect(await result.current.editSession.save()).toBe(true);
  });
  expect(line(result.current.project!).takes.at(-1)?.id).toBe("server-new-take");
  expect(line(result.current.project!).selectedTakeId).toBe("server-new-take");
  await act(async () => {
    result.current.editSession.update((p) => ({ ...p, title: "second edit" }));
    expect(await result.current.editSession.save()).toBe(true);
  });
  expect(mocks.saveProject).toHaveBeenCalledOnce();
  expect(mocks.patchProjectMetadata).toHaveBeenLastCalledWith(2, { title: "second edit" });
  expect(line(result.current.confirmedProject.current!).takes.at(-1)?.id).toBe("server-new-take");
});

it("rebases a queued save without losing newer committed edits or an incomplete draft", async () => {
  let finish!: (value: { revision: number }) => void;
  mocks.patchProjectLine.mockImplementationOnce(() => new Promise((resolve) => (finish = resolve)));
  const result = session();
  let first!: Promise<boolean>;
  let second!: Promise<boolean>;
  act(() => {
    const owner = result.current.editSession;
    owner.updateLine(line(fixture).id, { text: "確定した本文" });
    owner.commitLine(line(fixture).id);
    first = owner.save();
    owner.update((p) => ({ ...p, title: "次の保存" }));
    second = owner.save();
    owner.updateLine(line(fixture).id, { text: "" });
  });
  await act(async () => {
    finish({ revision: 1 });
    expect(await first).toBe(true);
    expect(await second).toBe(true);
  });
  expect(mocks.patchProjectMetadata).toHaveBeenCalledExactlyOnceWith(1, { title: "次の保存" });
  expect(mocks.saveProject).not.toHaveBeenCalled();
  expect(line(result.current.project!).text).toBe("確定した本文");
  expect(line(result.current.projectRef.current!).text).toBe("");
  expect(line(result.current.project!).selectedTakeId).toBeNull();
});

it("preserves a take selected after the save was sent", async () => {
  let finish!: (value: { revision: number }) => void;
  mocks.patchProjectLine.mockImplementationOnce(() => new Promise((resolve) => (finish = resolve)));
  const result = session();
  let saving!: Promise<boolean>;
  act(() => {
    const owner = result.current.editSession;
    owner.updateLine(line(fixture).id, { speechRate: 1.5 });
    saving = owner.save();
    owner.updateLine(line(fixture).id, { selectedTakeId: "user-choice" });
  });
  await act(async () => {
    finish({ revision: 1 });
    await saving;
  });
  expect(line(result.current.project!).selectedTakeId).toBe("user-choice");
});

it("ignores an acknowledgement after returning to a new visit of the same project", async () => {
  const result = session();
  const owner = result.current.editSession;
  const operation = owner.capture();
  act(() => {
    owner.replace({ ...project(), id: "other" });
    owner.replace({ ...project(), title: "reopened" });
    owner.recordSaved(operation, { ...project(), title: "obsolete", revision: 9 });
  });
  expect(result.current.project).toMatchObject({ title: "reopened", revision: 0 });
});

describe("recovering a failed save on an explicit request", () => {
  function noticeSession() {
    let shown = "";
    const setNotice = vi.fn((value: string | ((current: string) => string)) => {
      shown = typeof value === "function" ? value(shown) : value;
    });
    const { result } = renderHook(() => useProjectEditSession(setNotice));
    act(() => result.current.editSession.replace(project()));
    return { result, setNotice, shown: () => shown, show: (value: string) => setNotice(value) };
  }

  it("clears the stale save-failure notice when the silent retry succeeds", async () => {
    mocks.patchProjectMetadata.mockRejectedValueOnce(new Error("network down"));
    const { result, shown } = noticeSession();
    await act(async () => {
      result.current.editSession.update((p) => ({ ...p, title: "transient" }));
      expect(await result.current.editSession.save()).toBe(false);
    });
    expect(shown()).toBe("保存できませんでした: network down");
    await act(async () => {
      expect(await result.current.editSession.retryFailedSave()).toBe(true);
    });
    expect(shown()).toBe("");
  });

  it("keeps an unrelated notice that replaced the failure notice when the silent retry succeeds", async () => {
    mocks.patchProjectMetadata.mockRejectedValueOnce(new Error("network down"));
    const { result, shown, show } = noticeSession();
    await act(async () => {
      result.current.editSession.update((p) => ({ ...p, title: "transient" }));
      expect(await result.current.editSession.save()).toBe(false);
    });
    show("再生を停止しました。");
    await act(async () => {
      expect(await result.current.editSession.retryFailedSave()).toBe(true);
    });
    expect(shown()).toBe("再生を停止しました。");
  });

  it("re-sends the committed project after a transient failure and unblocks server operations", async () => {
    const notice = vi.fn();
    const { result } = renderHook(() => useProjectEditSession(notice));
    act(() => result.current.editSession.replace(project()));
    mocks.patchProjectMetadata.mockRejectedValueOnce(new Error("network down"));
    await act(async () => {
      result.current.editSession.update((p) => ({ ...p, title: "transient" }));
      expect(await result.current.editSession.save()).toBe(false);
    });
    expect(await result.current.editSession.waitForPersistence()).toBe(false);
    notice.mockClear();
    const action = vi.fn(async () => "ran");
    await act(async () => {
      expect(await result.current.editSession.retryFailedSave()).toBe(true);
      expect(await result.current.editSession.runServer(action)).toBe("ran");
    });
    expect(mocks.patchProjectMetadata).toHaveBeenCalledTimes(2);
    expect(mocks.patchProjectMetadata).toHaveBeenLastCalledWith(0, { title: "transient" });
    // The silent retry shows no message of its own; it only clears the earlier failure notice.
    expect(notice.mock.calls.filter(([value]) => typeof value === "string")).toEqual([]);
    expect(result.current.project!.title).toBe("transient");
  });

  it("silently re-saves the on-screen value over a same-field conflict at the server's current revision", async () => {
    const remote = project();
    remote.title = "remote title";
    remote.revision = 5;
    mocks.patchProjectMetadata.mockRejectedValueOnce(new ApiError("conflict", 409, { currentRevision: 5, currentProject: remote }, "project_revision_conflict", "http"));
    const { result, shown } = noticeSession();
    await act(async () => {
      result.current.editSession.update((p) => ({ ...p, title: "local title" }));
      expect(await result.current.editSession.save()).toBe(true);
    });
    expect(mocks.saveProject).toHaveBeenCalledOnce();
    expect(mocks.saveProject.mock.calls[0][0]).toMatchObject({ title: "local title", revision: 5 });
    // Same message as an ordinary save; no conflict notice.
    expect(shown()).toBe("保存しました");
    expect(result.current.project).toMatchObject({ title: "local title", revision: 6 });
    expect(result.current.confirmedProject.current).toMatchObject({ title: "local title", revision: 6 });
    // Server operations are not blocked afterwards.
    await act(async () => {
      expect(await result.current.editSession.retryFailedSave()).toBe(true);
    });
    expect(mocks.saveProject).toHaveBeenCalledOnce();
  });

  it("does not re-send when persistence is healthy", async () => {
    const result = session();
    await act(async () => {
      expect(await result.current.editSession.retryFailedSave()).toBe(true);
    });
    expect(mocks.saveProject).not.toHaveBeenCalled();
    expect(mocks.patchProjectMetadata).not.toHaveBeenCalled();
  });

  it("keeps blocking server operations when the re-save also fails", async () => {
    mocks.patchProjectMetadata.mockRejectedValue(new Error("still down"));
    const result = session();
    await act(async () => {
      result.current.editSession.update((p) => ({ ...p, title: "blocked" }));
      expect(await result.current.editSession.save()).toBe(false);
    });
    const action = vi.fn(async () => "ran");
    await act(async () => {
      expect(await result.current.editSession.retryFailedSave()).toBe(false);
      await expect(result.current.editSession.runServer(action)).rejects.toThrow("still down");
    });
    expect(mocks.patchProjectMetadata).toHaveBeenCalledTimes(2);
    expect(action).not.toHaveBeenCalled();
  });
});
