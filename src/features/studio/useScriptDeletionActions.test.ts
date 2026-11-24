import { expect, it, vi } from "vitest";
import type { CharacterActionModel } from "./studioCharacterActionTypes";
import type { StudioProject } from "../../types";
import { ProjectEditSession } from "./projectEditSession";
import { useScriptDeletionActions } from "./useScriptDeletionActions";

const mocks = vi.hoisted(() => ({ deleteLines: vi.fn(), priority: vi.fn(), reconcile: vi.fn() }));
vi.mock("../../api", () => ({ api: { deleteLines: mocks.deleteLines } }));
vi.mock("../shared/studio-utils", () => ({ confirmDestructiveAction: () => true }));
vi.mock("../script/scriptLineCapture", () => ({ waitForScriptLineSnapshots: async () => {}, prepareScriptLineSnapshots: vi.fn(), clearPreparedScriptLineSnapshots: vi.fn() }));
vi.mock("../script/scriptLineDeletionMotion", () => ({ beginScriptLineDeletion: () => ({ complete: vi.fn(), rollback: vi.fn() }) }));

it("deletes a line inside render priority and rebases queued work to the deletion revision", async () => {
  const line = { id: "deleted", text: "台詞", takes: [] };
  const project = { id: "project", revision: 1, scenes: [{ id: "scene", lines: [line] }], characters: [] } as unknown as StudioProject;
  const deleted = { ...project, revision: 2, scenes: [{ ...project.scenes[0], lines: [] }] };
  const session = new ProjectEditSession(() => {});
  session.replace(project);
  mocks.deleteLines.mockResolvedValue(deleted);
  let insidePriority = false;
  mocks.priority.mockImplementation(async (action: () => Promise<void>) => {
    insidePriority = true;
    await action();
    insidePriority = false;
  });
  mocks.deleteLines.mockImplementation(async () => {
    expect(insidePriority).toBe(true);
    return deleted;
  });
  const model = {
    editSession: session,
    setBusy: vi.fn(),
    setNotice: vi.fn(),
    runWithAutoRenderPriorityRef: { current: mocks.priority },
    reconcileAutoRenderQueueRef: { current: mocks.reconcile },
  } as unknown as CharacterActionModel;
  await useScriptDeletionActions(model).deleteLine("scene", project.scenes[0].lines[0]);
  expect(mocks.priority).toHaveBeenCalledOnce();
  expect(mocks.deleteLines).toHaveBeenCalledWith(["deleted"]);
  expect(mocks.reconcile).toHaveBeenCalledWith(2);
  expect(session.savedProject()?.scenes[0].lines).toEqual([]);
});
