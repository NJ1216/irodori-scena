import { useLayoutEffect, useMemo, useRef, useState } from "react";
import type { LinePronunciation } from "../../types";
import { codePoints, updatePronunciationsForText } from "./linePronunciations";
import { LineTextLocalHistory, type LineTextSnapshot } from "./lineTextLocalHistory";
import { editorText, selectionOffsets } from "./editorSelection";

const isReadingNode = (node: Node) => node.parentElement?.closest("rt") !== null;

function restoreCaret(root: HTMLElement, point: number) {
  root.focus({ preventScroll: true });
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, { acceptNode: (node) => (isReadingNode(node) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT) });
  let remaining = point;
  let node: Node | null;
  while ((node = walker.nextNode())) {
    const points = codePoints(node.textContent ?? "");
    if (remaining <= points.length) {
      const range = document.createRange();
      range.setStart(node, points.slice(0, remaining).join("").length);
      range.collapse(true);
      const selection = window.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(range);
      return;
    }
    remaining -= points.length;
  }
}

export function useLineTextEditing(value: string, normalized: LinePronunciation[], onChange: (text: string, pronunciations: LinePronunciation[]) => void) {
  const editor = useRef<HTMLDivElement>(null);
  const composing = useRef(false);
  const caret = useRef<number | null>(null);
  const beforeInputCaret = useRef<number | null>(null);
  const snapshot = useMemo<LineTextSnapshot>(() => ({ text: value, pronunciations: normalized }), [normalized, value]);
  const [history] = useState(() => new LineTextLocalHistory(snapshot));
  useLayoutEffect(() => {
    history.sync(snapshot);
    if (caret.current !== null && editor.current) {
      restoreCaret(editor.current, caret.current);
      caret.current = null;
    }
  }, [history, snapshot]);
  const changeLocally = (next: LineTextSnapshot, nextCaret: number | null = null) => {
    history.record(next, beforeInputCaret.current, nextCaret);
    beforeInputCaret.current = nextCaret;
    onChange(next.text, next.pronunciations);
  };
  const restoreLocalHistory = (direction: "undo" | "redo") => {
    const restored = direction === "undo" ? history.undo() : history.redo();
    if (!restored) return;
    caret.current = restored.caret;
    beforeInputCaret.current = restored.caret;
    onChange(restored.text, restored.pronunciations);
  };
  const input = () => {
    const root = editor.current;
    if (!root || composing.current) return;
    const selected = selectionOffsets(root);
    const next = editorText(root);
    caret.current = selected?.end ?? null;
    changeLocally({ text: next, pronunciations: updatePronunciationsForText(value, next, normalized) }, selected?.end ?? null);
  };
  return {
    editor,
    composing,
    changeLocally,
    restoreLocalHistory,
    input,
    onCompositionStart: () => {
      composing.current = true;
      beforeInputCaret.current = editor.current ? (selectionOffsets(editor.current)?.end ?? null) : null;
    },
    onCompositionEnd: () => {
      composing.current = false;
      input();
    },
    onBeforeInput: (root: HTMLElement) => {
      beforeInputCaret.current = selectionOffsets(root)?.end ?? null;
    },
  };
}
