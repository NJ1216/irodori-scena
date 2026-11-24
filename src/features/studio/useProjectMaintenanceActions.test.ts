import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api";
import type { StudioProject } from "../../types";
import type { CharacterActionModel } from "./studioCharacterActionTypes";
import { useProjectMaintenanceActions } from "./useProjectMaintenanceActions";

beforeEach(() => vi.restoreAllMocks());

function model() {
  const project = { scenes: [{ lines: [{ takes: [{ id: "one" }, { id: "two" }] }] }] } as StudioProject;
  const order: string[] = [];
  const autoGenerateEnabledRef = { current: true };
  // New-take intent now belongs to RenderJob, replacing the former ID set.
  const autoRenderQueue = {
    current: [
      { lineId: "line", cause: "manual-new-take", mode: "append" },
      { lineId: "other", cause: "manual-replace", mode: "replace" },
    ],
  };
  const owner = {
    project,
    clearTakesConfirm: true,
    autoGenerateEnabledRef,
    autoRenderQueue,
    stop: vi.fn(() => order.push("stop")),
    setBusy: vi.fn((value) => order.push(`busy:${value}`)),
    setWorkspace: vi.fn(),
    setNotice: vi.fn((value) => order.push(`notice:${value}`)),
    setAutoGenerateEnabled: vi.fn((value) => order.push(`auto:${value}`)),
    setClearTakesConfirm: vi.fn((value) => order.push(`confirm:${value}`)),
    editSession: {
      requestProject: vi.fn(async (request: () => Promise<StudioProject>) => {
        order.push("request");
        return request();
      }),
    },
  } as unknown as CharacterActionModel;
  return { owner, order, autoGenerateEnabledRef, autoRenderQueue };
}

it("clears takes before resetting automatic generation state and releasing busy", async () => {
  const fixture = model();
  vi.spyOn(api, "clearAllTakes").mockImplementation(async () => {
    fixture.order.push("api");
    return fixture.owner.project!;
  });
  await useProjectMaintenanceActions(fixture.owner).clearAllTakes(true);
  expect(fixture.order).toEqual(["stop", "busy:clear-takes", "request", "api", "auto:false", expect.stringMatching(/^notice:2 件の生成テイクを削除しました/), "confirm:false", "busy:null"]);
  expect(fixture.autoGenerateEnabledRef.current).toBe(false);
  expect(fixture.autoRenderQueue.current).toEqual([]);
});

it("only opens confirmation before a non-forced clear", async () => {
  const fixture = model();
  (fixture.owner as CharacterActionModel & { clearTakesConfirm: boolean }).clearTakesConfirm = false;
  const clear = vi.spyOn(api, "clearAllTakes");
  await useProjectMaintenanceActions(fixture.owner).clearAllTakes();
  expect(fixture.order).toEqual(["confirm:true"]);
  expect(clear).not.toHaveBeenCalled();
});

it("starts a new project with automatic generation enabled", async () => {
  const fixture = model();
  fixture.autoGenerateEnabledRef.current = false;
  fixture.owner.editSession.runServer = vi.fn(async (request: () => Promise<Awaited<ReturnType<typeof api.createNewProject>>>, reflect: (result: Awaited<ReturnType<typeof api.createNewProject>>) => void) => {
    const result = await request();
    reflect(result);
    return result;
  }) as unknown as typeof fixture.owner.editSession.runServer;
  fixture.owner.editSession.replace = vi.fn();
  const response = { project: fixture.owner.project!, workspace: { path: "/tmp/new.scena", name: "new.scena", isScratch: true } } as Awaited<ReturnType<typeof api.createNewProject>>;
  vi.spyOn(api, "createNewProject").mockResolvedValue(response);

  await useProjectMaintenanceActions(fixture.owner).createNewProject();

  expect(fixture.autoGenerateEnabledRef.current).toBe(true);
  expect(fixture.owner.editSession.replace).toHaveBeenCalledWith(response.project);
  expect(fixture.owner.setWorkspace).toHaveBeenCalledWith(response.workspace);
  expect(fixture.owner.setAutoGenerateEnabled).toHaveBeenCalledWith(true);
  expect(fixture.autoRenderQueue.current).toEqual([]);
});
