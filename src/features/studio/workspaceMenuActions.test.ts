import { beforeEach, describe, expect, it, vi } from "vitest";

const { chooseProjectBackupDestination, chooseProjectFile, backupWorkspace, optimizeWorkspace, openWorkspace, prepareDerivedAudio } = vi.hoisted(() => ({
  chooseProjectBackupDestination: vi.fn(),
  backupWorkspace: vi.fn(),
  optimizeWorkspace: vi.fn(),
  chooseProjectFile: vi.fn(),
  openWorkspace: vi.fn(),
  prepareDerivedAudio: vi.fn().mockResolvedValue({ projectKey: "test", boundaries: [] }),
}));
vi.mock("../../api", () => ({
  api: { backupWorkspace, optimizeWorkspace, openWorkspace, prepareDerivedAudio },
  chooseDirectory: vi.fn(),
  chooseProjectBackupDestination,
  chooseProjectFile,
  isDesktopRuntime: true,
}));

import { backupWorkspaceAction, openWorkspaceAction, optimizeWorkspaceAction, projectBackupDefaultName } from "./workspaceMenuActions";

describe("project optimization", () => {
  beforeEach(() => vi.clearAllMocks());

  it("flushes edits and reports the reduced file size", async () => {
    const project = { title: "作品" };
    optimizeWorkspace.mockResolvedValue({ project, beforeBytes: 12_000_000, afterBytes: 9_000_000 });
    const stop = vi.fn();
    const restore = vi.fn();
    const setNotice = vi.fn();
    const setBusy = vi.fn();
    await optimizeWorkspaceAction({
      workspace: { path: "/tmp/current.scena", name: "current.scena", isScratch: false },
      stop,
      setNotice,
      setBusy,
      editSession: {
        runServer: async (request: () => Promise<unknown>, reflect: (value: any, operation: object) => void) => {
          const value = await request();
          reflect(value, {});
          return value;
        },
        restore,
      },
    } as never);
    expect(stop).toHaveBeenCalledOnce();
    expect(optimizeWorkspace).toHaveBeenCalledOnce();
    expect(restore).toHaveBeenCalledWith({}, project);
    expect(setNotice).toHaveBeenLastCalledWith("最適化保存しました。ファイルを約3.0 MB小さくしました。");
    expect(setBusy).toHaveBeenLastCalledWith(null);
  });

  it("requires a saved project", async () => {
    const setNotice = vi.fn();
    await optimizeWorkspaceAction({ workspace: { isScratch: true }, setNotice } as never);
    expect(optimizeWorkspace).not.toHaveBeenCalled();
    expect(setNotice).toHaveBeenCalledWith("先にプロジェクトを保存してください。");
  });
});

describe("project backup", () => {
  beforeEach(() => vi.clearAllMocks());
  it("uses the saved folder name or a sanitized project title", () => {
    expect(projectBackupDefaultName({ path: "/tmp/current.scena", name: "current.scena", isScratch: false }, "別名")).toBe("current.scena");
    expect(projectBackupDefaultName({ path: "/tmp/scena-data", name: "scena-data（未保存）", isScratch: true }, " 作品/第一話. ")).toBe("作品_第一話.scena");
  });

  it("reconciles the project without changing the workspace", async () => {
    const project = { title: "作品" };
    const updated = { title: "作品", revision: 2 };
    const workspace = { path: "/tmp/current.scena", name: "current.scena", isScratch: false };
    chooseProjectBackupDestination.mockResolvedValue("/tmp/copy.scena");
    backupWorkspace.mockResolvedValue({ project: updated, backup: { path: "/tmp/copy.scena", name: "copy.scena" } });
    const restore = vi.fn();
    const setWorkspace = vi.fn();
    const setNotice = vi.fn();
    const setBusy = vi.fn();
    const operation = {};
    const model = {
      workspace,
      projectRef: { current: project },
      setBusy,
      setNotice,
      setWorkspace,
      setDraftJob: vi.fn(),
      setExportJob: vi.fn(),
      setGlobalCastUpdates: vi.fn(),
      stop: vi.fn(),
      editSession: {
        restore,
        runServer: async (request: () => Promise<unknown>, reconcile: (value: any, operation: object) => void) => {
          const value = await request();
          reconcile(value, operation);
          return value;
        },
      },
    };

    await backupWorkspaceAction(model as never);

    expect(backupWorkspace).toHaveBeenCalledWith("/tmp/copy.scena");
    expect(restore).toHaveBeenCalledWith(operation, updated);
    expect(setWorkspace).not.toHaveBeenCalled();
    expect(setNotice).toHaveBeenCalledWith("「copy.scena」へバックアップしました。現在の保存先は変更していません。");
    expect(setBusy).toHaveBeenLastCalledWith(null);
  });

  it("does nothing after save-panel cancellation", async () => {
    chooseProjectBackupDestination.mockResolvedValue(null);
    const setBusy = vi.fn();
    await backupWorkspaceAction({
      workspace: null,
      projectRef: { current: { title: "作品" } },
      setBusy,
      setNotice: vi.fn(),
      setWorkspace: vi.fn(),
      setDraftJob: vi.fn(),
      setExportJob: vi.fn(),
      setGlobalCastUpdates: vi.fn(),
      stop: vi.fn(),
      editSession: { runServer: vi.fn() },
    } as never);
    expect(backupWorkspace).not.toHaveBeenCalled();
    expect(setBusy).toHaveBeenLastCalledWith(null);
  });

  it("asks to save an unsaved project before choosing a backup destination", async () => {
    const setNotice = vi.fn();
    await backupWorkspaceAction({
      workspace: { path: "/tmp/scena-data", name: "scena-data（未保存）", isScratch: true },
      projectRef: { current: { title: "作品" } },
      setBusy: vi.fn(),
      setNotice,
      setWorkspace: vi.fn(),
      setDraftJob: vi.fn(),
      setExportJob: vi.fn(),
      setGlobalCastUpdates: vi.fn(),
      stop: vi.fn(),
      editSession: { runServer: vi.fn() },
    } as never);
    expect(chooseProjectBackupDestination).not.toHaveBeenCalled();
    expect(backupWorkspace).not.toHaveBeenCalled();
    expect(setNotice).toHaveBeenCalledWith("先にプロジェクトを保存してください。");
  });
});

describe("project workspace actions", () => {
  beforeEach(() => vi.clearAllMocks());

  it("reports an API failure without changing the workspace", async () => {
    chooseProjectBackupDestination.mockResolvedValue("/tmp/copy.scena");
    backupWorkspace.mockRejectedValue(new Error("配置できません"));
    const setNotice = vi.fn();
    const setWorkspace = vi.fn();
    await backupWorkspaceAction({
      workspace: { path: "/tmp/current.scena", name: "current.scena", isScratch: false },
      projectRef: { current: { title: "作品" } },
      setBusy: vi.fn(),
      setNotice,
      setWorkspace,
      setDraftJob: vi.fn(),
      setExportJob: vi.fn(),
      setGlobalCastUpdates: vi.fn(),
      stop: vi.fn(),
      editSession: { runServer: (request: () => Promise<unknown>) => request() },
    } as never);
    expect(setWorkspace).not.toHaveBeenCalled();
    expect(setNotice).toHaveBeenCalledWith("プロジェクトをバックアップできませんでした: 配置できません");
  });

  it("opens a direct project path without showing the picker", async () => {
    const project = { id: "project", revision: 2 };
    openWorkspace.mockResolvedValue({ project, workspace: { name: "direct.scena" }, globalCastUpdates: [] });
    const replace = vi.fn();
    const model = {
      setBusy: vi.fn(),
      setNotice: vi.fn(),
      setWorkspace: vi.fn(),
      setDraftJob: vi.fn(),
      setExportJob: vi.fn(),
      setGlobalCastUpdates: vi.fn(),
      stop: vi.fn(),
      editSession: {
        replace,
        runServer: async (request: () => Promise<unknown>, reflect: (value: any) => void) => {
          const value = await request();
          reflect(value);
          return value;
        },
      },
    };
    await openWorkspaceAction(model as never, "/tmp/direct.scena");
    expect(chooseProjectFile).not.toHaveBeenCalled();
    expect(openWorkspace).toHaveBeenCalledWith("/tmp/direct.scena");
    expect(replace).toHaveBeenCalledWith(project);
  });
});
