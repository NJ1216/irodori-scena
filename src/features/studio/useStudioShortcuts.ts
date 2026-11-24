import { primaryModifier } from "../shared/platform";
import { useEffect } from "react";
import { numberedScriptLines } from "../script/scriptLineNumbers";
import { requestScriptSearch } from "../script/scriptSearchEvents";
import { requestExpressionPaletteToggle } from "../script/expressionPaletteEvents";
import type { ProjectWorkspace, StudioProject } from "../../types";
import { sceneLabel } from "../shared/studio-utils";
import { showLineJumpInput } from "./lineJumpEvents";

type ShortcutModel = {
  project: StudioProject | null;
  projectRef: { current: StudioProject | null };
  workspace: ProjectWorkspace | null;
  tab: string;
  focusedLineId: string | null;
  selectedLineIds: string[];
  selectionAnchorLineId: string | null;
  busy: string | null;
  autoGenerateEnabled: boolean;
  continuousPlayback: boolean;
  playingLineId: string | null;
  selectedLinePlaybackPending: { current: boolean };
  selectedLineGenerationActive: boolean;
  autoRenderInProgress: { current: boolean };
  autoScrollTarget: "playback" | "export";
  autoScrollEnabled: boolean;
  setNotice: (message: string) => void;
  setFocusedLineId: (lineId: string | null) => void;
  setSelectedLineIds: (lineIds: string[]) => void;
  setSelectionAnchorLineId: (lineId: string | null) => void;
  setAutoScrollTarget: (target: "playback" | "export") => void;
  setAutoScrollEnabled: (enabled: boolean) => void;
  requestProjectMenuAction: (action: "new") => void;
  openWorkspace: () => Promise<void>;
  saveWorkspace: () => Promise<void>;
  deleteSelectedLines: () => Promise<void>;
  generateSelectedLines: (replace: boolean, sourceLineId?: string | null, playAfter?: boolean) => Promise<void>;
  cancelSelectedLineGeneration: () => Promise<void>;
  playSelected: (sourceLineId?: string | null) => Promise<void>;
  play: (url: string, lineId?: string) => void;
  playContinuous: () => Promise<void>;
  stop: () => void;
  toggleAutoGeneration: () => void;
};

function shortcutBlocked(event: KeyboardEvent) {
  if (event.isComposing || document.querySelector('.modal-backdrop, [role="dialog"][aria-modal="true"]')) return true;
  const target = event.target as HTMLElement | null;
  return Boolean(target?.closest("input, textarea, select, [contenteditable='true']"));
}

function isStudioShortcut(event: KeyboardEvent) {
  if (!primaryModifier(event)) return !event.metaKey && !event.ctrlKey && !event.altKey && event.code === "Space";
  return ["KeyA", "KeyN", "KeyO", "KeyS", "KeyR", "KeyP"].includes(event.code);
}

function isPlaybackShortcut(event: KeyboardEvent) {
  if (!event.metaKey && !event.ctrlKey && event.code === "Space") return true;
  return primaryModifier(event) && event.code === "KeyP";
}

function isRubyShortcut(event: KeyboardEvent) {
  return primaryModifier(event) && event.code === "KeyR" && !event.shiftKey && !event.altKey;
}

function isTextInput(event: KeyboardEvent) {
  return Boolean((event.target as HTMLElement | null)?.closest("input, textarea, select, [contenteditable='true']"));
}

function shouldIgnoreShortcut(event: KeyboardEvent, model: ShortcutModel) {
  if (shortcutBlocked(event)) {
    const lineRubyShortcut = isRubyShortcut(event) && (event.target as HTMLElement | null)?.closest(".line-text-editor");
    if (isStudioShortcut(event) && event.code !== "KeyA" && !lineRubyShortcut && !(event.code === "Space" && isTextInput(event))) event.preventDefault();
    return true;
  }
  if (model.busy && !model.autoRenderInProgress.current && !isPlaybackShortcut(event)) {
    if (isStudioShortcut(event)) event.preventDefault();
    return true;
  }
  return false;
}

function handleProjectShortcut(event: KeyboardEvent, model: ShortcutModel) {
  if (event.code === "KeyN" && !event.shiftKey && !event.altKey) {
    event.preventDefault();
    model.requestProjectMenuAction("new");
    return true;
  }
  if (event.code === "KeyO" && !event.shiftKey && !event.altKey) {
    event.preventDefault();
    void model.openWorkspace();
    return true;
  }
  if (event.code !== "KeyS" || event.shiftKey || event.altKey || !model.workspace?.isScratch) return false;
  event.preventDefault();
  void model.saveWorkspace();
  return true;
}

function handleLineShortcut(event: KeyboardEvent, model: ShortcutModel) {
  const sourceLineId = model.focusedLineId ?? model.selectedLineIds.at(-1) ?? null;
  if (event.code === "KeyR") {
    if (event.shiftKey === event.altKey) return;
    event.preventDefault();
    if (model.busy && !model.autoRenderInProgress.current) return;
    void model.generateSelectedLines(event.shiftKey, sourceLineId);
    return;
  }
  if (event.code !== "KeyP") return;
  event.preventDefault();
  if (!sourceLineId || (event.shiftKey && event.altKey)) return;
  if (event.shiftKey || event.altKey) {
    if (model.busy && !model.autoRenderInProgress.current) return;
    void model.generateSelectedLines(event.shiftKey, sourceLineId, true);
    return;
  }
  void model.playSelected(sourceLineId);
}

function moveLineSelection(event: KeyboardEvent, model: ShortcutModel) {
  if (event.code !== "ArrowDown" && event.code !== "ArrowUp") return false;
  const project = model.projectRef.current;
  const lines = project?.scenes.flatMap((scene) => scene.lines.map((line) => line.id)) ?? [];
  const currentId = model.focusedLineId ?? model.selectedLineIds.at(-1) ?? "";
  const currentIndex = currentId ? lines.indexOf(currentId) : -1;
  if (currentIndex < 0) return false;
  const nextIndex = Math.max(0, Math.min(lines.length - 1, currentIndex + (event.code === "ArrowDown" ? 1 : -1)));
  const nextId = lines[nextIndex];
  if (!nextId) return false;
  event.preventDefault();
  const anchorId = event.shiftKey ? (model.selectionAnchorLineId ?? currentId) : nextId;
  const anchorIndex = lines.indexOf(anchorId);
  const start = Math.min(anchorIndex, nextIndex);
  const end = Math.max(anchorIndex, nextIndex);
  model.setFocusedLineId(nextId);
  model.setSelectedLineIds(event.shiftKey ? lines.slice(start, end + 1) : [nextId]);
  model.setSelectionAnchorLineId(anchorId);
  window.requestAnimationFrame(() => {
    const card = Array.from(document.querySelectorAll<HTMLElement>("article[data-line-id]")).find((element) => element.dataset.lineId === nextId);
    if (!card) return;
    card.dataset.shortcutFocus = "true";
    card.focus();
  });
  return true;
}

function handleSelectionShortcut(event: KeyboardEvent, model: ShortcutModel) {
  if (moveLineSelection(event, model)) return true;
  if (!["Delete", "Backspace"].includes(event.code) || !model.selectedLineIds.length) return false;
  event.preventDefault();
  void model.deleteSelectedLines();
  return true;
}

type SelectionShortcutModel = Pick<ShortcutModel, "tab" | "focusedLineId" | "selectedLineIds" | "setFocusedLineId" | "setSelectedLineIds" | "setSelectionAnchorLineId">;

export function clearMultipleSelection(event: KeyboardEvent, model: SelectionShortcutModel) {
  if (event.key !== "Escape" || model.tab !== "script" || model.selectedLineIds.length < 2) return false;
  if (event.isComposing || document.querySelector('.modal-backdrop, [role="dialog"][aria-modal="true"]')) return false;
  const lineId = model.focusedLineId && model.selectedLineIds.includes(model.focusedLineId) ? model.focusedLineId : model.selectedLineIds[0];
  event.preventDefault();
  model.setFocusedLineId(lineId ?? null);
  model.setSelectedLineIds(lineId ? [lineId] : []);
  model.setSelectionAnchorLineId(lineId ?? null);
  return true;
}

function cancelSelectedGeneration(event: KeyboardEvent, model: Pick<ShortcutModel, "selectedLineGenerationActive" | "cancelSelectedLineGeneration">) {
  if (event.key !== "Escape" || !model.selectedLineGenerationActive || event.isComposing) return false;
  if (document.querySelector('.modal-backdrop, [role="dialog"][aria-modal="true"]')) return false;
  event.preventDefault();
  void model.cancelSelectedLineGeneration();
  return true;
}

function toggleExpressionPalette(event: KeyboardEvent) {
  if (event.code !== "F3" || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey || event.isComposing) return false;
  if (document.querySelector('.modal-backdrop, [role="dialog"][aria-modal="true"]') || document.documentElement.classList.contains("is-dragging-expression-emoji")) return false;
  event.preventDefault();
  requestExpressionPaletteToggle();
  return true;
}

function selectAllLines(event: KeyboardEvent, model: ShortcutModel) {
  if (event.code !== "KeyA" || event.shiftKey || event.altKey) return false;
  const lineIds = model.projectRef.current?.scenes.flatMap((scene) => scene.lines.map((line) => line.id)) ?? [];
  if (!lineIds.length) return false;
  event.preventDefault();
  const focused = lineIds.includes(model.focusedLineId ?? "") ? model.focusedLineId : lineIds[0];
  model.setFocusedLineId(focused);
  model.setSelectedLineIds(lineIds);
  model.setSelectionAnchorLineId(focused);
  return true;
}

function handleNonCommandShortcut(event: KeyboardEvent, model: ShortcutModel) {
  if (model.tab === "script" && handleSelectionShortcut(event, model)) return true;
  if (event.code !== "Space") return false;
  event.preventDefault();
  if (model.continuousPlayback) model.stop();
  else void model.playContinuous();
  return true;
}

function cycleAutoGenerationFollow(model: ShortcutModel) {
  if (!model.autoGenerateEnabled) {
    model.setAutoScrollTarget("export");
    model.setAutoScrollEnabled(true);
    model.toggleAutoGeneration();
  } else if (model.autoScrollEnabled && model.autoScrollTarget === "export") {
    model.setAutoScrollEnabled(false);
    model.setNotice("自動生成FollowをOFFにしました。自動生成は継続します。");
  } else {
    model.toggleAutoGeneration();
  }
}

function toggleFollow(event: KeyboardEvent, model: ShortcutModel) {
  if (shortcutBlocked(event) || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return false;
  if (event.code === "KeyR") {
    event.preventDefault();
    cycleAutoGenerationFollow(model);
    return true;
  }
  if (event.code !== "KeyF" || model.tab !== "script") return false;
  event.preventDefault();
  const target = "playback";
  const enabled = !(model.autoScrollEnabled && model.autoScrollTarget === target);
  model.setAutoScrollTarget(target);
  model.setAutoScrollEnabled(enabled);
  model.setNotice(enabled ? "再生FollowをONにしました。連続再生時に発話行を追従します。" : "再生FollowをOFFにしました。");
  return true;
}

function handleCommandShortcut(event: KeyboardEvent, model: ShortcutModel) {
  if (model.tab === "script" && selectAllLines(event, model)) return;
  if (handleProjectShortcut(event, model)) return;
  if (model.tab !== "script") return;
  if (event.altKey && !["KeyP", "KeyR", "Enter"].includes(event.code)) return;
  handleLineShortcut(event, model);
}

type JumpState = { value: string; timer?: number };
function clearJump(state: JumpState) {
  state.value = "";
  if (state.timer) window.clearTimeout(state.timer);
  state.timer = undefined;
  showLineJumpInput(null);
}

function focusJumpTarget(model: ShortcutModel, lineId: string) {
  model.setFocusedLineId(lineId);
  model.setSelectedLineIds([lineId]);
  model.setSelectionAnchorLineId(lineId);
  requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-line-id="${CSS.escape(lineId)}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" }));
}

function completeLineJump(model: ShortcutModel, state: JumpState, input: string) {
  const number = Number(input);
  const target = model.projectRef.current && numberedScriptLines(model.projectRef.current).find((item) => item.number === number);
  clearJump(state);
  if (!target) {
    model.setNotice(number === 0 ? "発話行番号0はありません。" : `発話行番号${number}はありません。`);
    return;
  }
  focusJumpTarget(model, target.lineId);
}

function completeSceneJump(model: ShortcutModel, state: JumpState, input: string) {
  const normalized = input.toLocaleLowerCase("en-US");
  const scene = model.projectRef.current?.scenes.find((_, index) => sceneLabel(index).toLocaleLowerCase("en-US") === normalized);
  clearJump(state);
  if (!scene) {
    model.setNotice(`シーン${input}はありません。`);
    return;
  }
  const firstLine = scene.lines[0];
  if (!firstLine) {
    model.setNotice(`シーン${sceneLabel(model.projectRef.current?.scenes.indexOf(scene) ?? 0)}に発話行がありません。`);
    return;
  }
  focusJumpTarget(model, firstLine.id);
}

function completeJump(model: ShortcutModel, state: JumpState) {
  const input = state.value.slice(1);
  if (/^\d+$/.test(input)) completeLineJump(model, state, input);
  else completeSceneJump(model, state, input);
}
// The finite-state parser deliberately handles start, digits, completion,
// cancellation, invalid input, and destination validation in one place.
// eslint-disable-next-line complexity
function handleDirectJump(event: KeyboardEvent, model: ShortcutModel, state: JumpState) {
  if (model.tab !== "script" || shortcutBlocked(event) || event.metaKey || event.ctrlKey || event.altKey) return false;
  if (event.key === "Escape" && state.value) {
    event.preventDefault();
    clearJump(state);
    return true;
  }
  if (!state.value && event.key !== ".") return false;
  if (state.value === "" && event.key === ".") state.value = ".";
  else if (/^\.[A-Za-z0-9]*$/.test(state.value) && /^[A-Za-z0-9]$/.test(event.key)) state.value += event.key;
  else if (/^\.[A-Za-z0-9]+$/.test(state.value) && (event.key === "." || event.key === "Enter")) {
    event.preventDefault();
    completeJump(model, state);
    return true;
  } else {
    clearJump(state);
    return false;
  }
  event.preventDefault();
  showLineJumpInput(state.value);
  if (state.timer) window.clearTimeout(state.timer);
  state.timer = window.setTimeout(() => clearJump(state), 3000);
  return true;
}

export function useStudioShortcuts(model: ShortcutModel) {
  useEffect(() => {
    const jump: JumpState = { value: "" };
    const onKeyDown = (event: KeyboardEvent) => {
      if (toggleExpressionPalette(event)) return;
      if (cancelSelectedGeneration(event, model)) return;
      if (clearMultipleSelection(event, model)) return;
      if (model.tab === "script" && primaryModifier(event) && !event.altKey && event.code === "KeyF" && !document.querySelector('.modal-backdrop, [role="dialog"][aria-modal="true"]')) {
        event.preventDefault();
        requestScriptSearch();
        return;
      }
      if (handleDirectJump(event, model, jump)) return;
      if (toggleFollow(event, model)) return;
      if (shouldIgnoreShortcut(event, model)) return;
      const command = primaryModifier(event);
      if (!command && handleNonCommandShortcut(event, model)) return;
      if (!command) return;
      handleCommandShortcut(event, model);
    };
    window.addEventListener("keydown", onKeyDown, true);
    return () => {
      clearJump(jump);
      window.removeEventListener("keydown", onKeyDown, true);
    };
  }, [model]);
}
