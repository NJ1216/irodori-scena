import { describe, expect, it, vi } from "vitest";

import { projectMenuActionDisabled, useProjectMenuActions } from "./projectMenuActions";
import { projectMenuActionLabel } from "./projectMenuActionTypes";

describe("project menu actions", () => {
  it("uses descriptive labels in the auto-generation conflict dialog", () => {
    expect(projectMenuActionLabel.export).toBe("エクスポート");
    expect(projectMenuActionLabel["project-backup"]).toBe("プロジェクトのバックアップ");
    expect(projectMenuActionLabel.optimize).toBe("最適化保存");
    expect(Object.values(projectMenuActionLabel)).not.toContain("台本初期化");
  });

  it("keeps the menu enabled only while auto-generation is active", () => {
    expect(projectMenuActionDisabled("line-1", true)).toBe(false);
    expect(projectMenuActionDisabled("draft", false)).toBe(true);
  });

  it("stops auto-generation before continuing the selected action", async () => {
    const stopAutoGeneration = vi.fn().mockResolvedValue(undefined);
    const execute = vi.fn();
    let pendingAction: "script-import" | null = null;
    const actions = useProjectMenuActions({
      autoGenerateEnabled: true,
      autoRenderInProgress: { current: true },
      autoRenderQueue: { current: [] },
      pendingAction,
      setPendingAction: (action) => {
        pendingAction = action as typeof pendingAction;
      },
      stopAutoGeneration,
      execute,
      onFailure: vi.fn(),
    });

    actions.requestProjectMenuAction("script-import");
    expect(pendingAction).toBe("script-import");
    const confirmed = useProjectMenuActions({
      autoGenerateEnabled: true,
      autoRenderInProgress: { current: true },
      autoRenderQueue: { current: [] },
      pendingAction,
      setPendingAction: (action) => {
        pendingAction = action as typeof pendingAction;
      },
      stopAutoGeneration,
      execute,
      onFailure: vi.fn(),
    });
    await confirmed.continueProjectMenuAction();

    expect(stopAutoGeneration).toHaveBeenCalledOnce();
    expect(execute).toHaveBeenCalledWith("script-import", true);
  });

  function useMenuWith(state: { enabled: boolean; inProgress: boolean; queued: number }) {
    const execute = vi.fn();
    const setPendingAction = vi.fn();
    const actions = useProjectMenuActions({
      autoGenerateEnabled: state.enabled,
      autoRenderInProgress: { current: state.inProgress },
      autoRenderQueue: { current: Array.from({ length: state.queued }, (_, index) => ({ lineId: `line-${index}` })) },
      pendingAction: null,
      setPendingAction,
      stopAutoGeneration: vi.fn(),
      execute,
      onFailure: vi.fn(),
    });
    return { actions, execute, setPendingAction };
  }

  it("runs the action at once while auto-generation is on but idle", () => {
    const { actions, execute, setPendingAction } = useMenuWith({ enabled: true, inProgress: false, queued: 0 });
    actions.requestProjectMenuAction("new");
    expect(execute).toHaveBeenCalledWith("new", false);
    expect(setPendingAction).not.toHaveBeenCalled();
  });

  it("asks before discarding queued auto-generation work", () => {
    const { actions, execute, setPendingAction } = useMenuWith({ enabled: true, inProgress: false, queued: 2 });
    actions.requestProjectMenuAction("new");
    expect(setPendingAction).toHaveBeenCalledWith("new");
    expect(execute).not.toHaveBeenCalled();
  });

  it("asks while an auto-generated take is being rendered", () => {
    const { actions, execute, setPendingAction } = useMenuWith({ enabled: true, inProgress: true, queued: 0 });
    actions.requestProjectMenuAction("open");
    expect(setPendingAction).toHaveBeenCalledWith("open");
    expect(execute).not.toHaveBeenCalled();
  });
});
