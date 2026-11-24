import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { primaryModifier } from "../shared/platform";
import { editorCaretOffset, editorText } from "./editorSelection";
import type { ScriptViewProps } from "./ScriptViewTypes";

function lineTextEditorTarget(target: EventTarget | null) {
  return target instanceof HTMLElement && target.matches(".line-text-editor") ? target : null;
}

export function useScriptEditorKeyboard({ project, onCommitLineContent, onSplitLine, onQueueAutoRender }: Pick<ScriptViewProps, "project" | "onCommitLineContent" | "onSplitLine" | "onQueueAutoRender">) {
  const splitLine = (textarea: HTMLElement) => {
    const lineId = textarea.closest<HTMLElement>("[data-line-id]")?.dataset.lineId;
    const location = lineId ? project.scenes.map((scene) => ({ scene, index: scene.lines.findIndex((line) => line.id === lineId) })).find((item) => item.index >= 0) : undefined;
    if (!location || !lineId) return;
    const offset = editorCaretOffset(textarea);
    if (offset === null) return;
    const atEnd = offset === Array.from(editorText(textarea)).length;
    void (async () => {
      if ((await onCommitLineContent(lineId, false)) && (await onSplitLine(location.scene.id, lineId, offset))) {
        if (atEnd) onQueueAutoRender(lineId);
      }
    })();
  };
  const moveFocus = (textarea: HTMLElement, backwards: boolean) => {
    const textareas = Array.from(document.querySelectorAll<HTMLElement>(".script-canvas .line-text-editor"));
    const currentIndex = textareas.indexOf(textarea);
    if (currentIndex < 0 || textareas.length === 0) return false;
    const step = backwards ? -1 : 1;
    textareas[(currentIndex + step + textareas.length) % textareas.length].focus();
    return true;
  };
  return (event: ReactKeyboardEvent<HTMLElement>) => {
    const textarea = lineTextEditorTarget(event.target);
    if (!textarea || !textarea.closest(".line-main")) return;
    if (primaryModifier(event) && event.key === "Enter") {
      event.preventDefault();
      splitLine(textarea);
      return;
    }
    if (event.key !== "Tab" || event.metaKey || event.ctrlKey || event.altKey) return;
    if (moveFocus(textarea, event.shiftKey)) event.preventDefault();
  };
}
