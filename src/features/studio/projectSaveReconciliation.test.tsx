import { act, renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
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
