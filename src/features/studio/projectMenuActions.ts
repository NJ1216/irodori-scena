import type { ProjectMenuAction } from "./projectMenuActionTypes";

export function projectMenuActionDisabled(busy: string | null, autoGenerateEnabled: boolean, importing = false) {
  return (Boolean(busy) && !autoGenerateEnabled) || importing;
}

type MenuActions = {
  autoGenerateEnabled: boolean;
  autoRenderInProgress: { current: boolean };
  autoRenderQueue: { current: readonly unknown[] };
  pendingAction: ProjectMenuAction | null;
  setPendingAction: (action: ProjectMenuAction | null) => void;
  stopAutoGeneration: () => Promise<void>;
  execute: (action: ProjectMenuAction, afterAutoStop: boolean) => void;
  onFailure: (error: Error) => void;
};

export function useProjectMenuActions(model: MenuActions) {
  function requestProjectMenuAction(action: ProjectMenuAction) {
    // Ask only when stopping would discard work: an auto take is rendering or lines wait in the queue.
    if (!model.autoRenderInProgress.current && model.autoRenderQueue.current.length === 0) {
      model.execute(action, false);
      return;
    }
    model.setPendingAction(action);
  }

  async function continueProjectMenuAction() {
    const action = model.pendingAction;
    if (!action) return;
    model.setPendingAction(null);
    try {
      await model.stopAutoGeneration();
      model.execute(action, true);
    } catch (error) {
      model.onFailure(error as Error);
    }
  }

  return { requestProjectMenuAction, continueProjectMenuAction };
}
