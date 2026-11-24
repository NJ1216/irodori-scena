import { insertIntoLineEditor, type LineTextEditorElement } from "../script/EmojiTextArea";
import type { AutoScrollTarget, Tab } from "./types";
import type { StudioState } from "./useStudioState";

type InteractionModel = Pick<StudioState, "tabRef" | "focusedTextInput" | "autoGenerateEnabledRef" | "tab" | "setTab" | "setNotice" | "busy" | "continuousPlayback" | "autoScrollEnabled" | "setPlaybackHoverFollow" | "setExportHoverFollow">;
export function useStudioEditingInteractions(model: InteractionModel, clearCandidates: (showNotice?: boolean) => Promise<void>) {
  const { tabRef, focusedTextInput, autoGenerateEnabledRef, tab, setTab, setNotice, busy, continuousPlayback, autoScrollEnabled, setPlaybackHoverFollow, setExportHoverFollow } = model;
  function enableAutoScroll(target: AutoScrollTarget) {
    const actionIsActive = target === "playback" ? continuousPlayback : busy === "export" || autoGenerateEnabledRef.current;
    if (!actionIsActive) return;
    if (autoScrollEnabled) return;
    if (target === "playback") {
      setPlaybackHoverFollow(true);
      return;
    }
    setExportHoverFollow(true);
  }

  function disablePlaybackHoverFollow() {
    setPlaybackHoverFollow(false);
  }

  function disableExportHoverFollow() {
    setExportHoverFollow(false);
  }

  function changeTab(next: Tab) {
    if (busy === "draft" && next !== tab) {
      setNotice("AI台本の生成中は、台本画面を固定しています。完了後に音声合成を再開できます。");
      return;
    }
    if (tab === "characters" && next !== "characters") {
      void clearCandidates(false);
    }
    tabRef.current = next;
    setTab(next);
  }

  function rememberTextFocus(sceneId: string, lineId: string, element: LineTextEditorElement) {
    focusedTextInput.current = { sceneId, lineId, element };
  }

  function insertExpressionEmoji(emoji: string) {
    const active = focusedTextInput.current;
    if (!active || document.activeElement !== active.element) return;
    insertIntoLineEditor(active.element, emoji);
  }

  return { enableAutoScroll, disablePlaybackHoverFollow, disableExportHoverFollow, changeTab, rememberTextFocus, insertExpressionEmoji };
}
