import { useEffect, useState, type RefObject } from "react";
import type { LinePronunciation } from "../../types";
import { codePoints, normalizeLinePronunciations, selectionConflict } from "./linePronunciations";
import type { LineTextSnapshot } from "./lineTextLocalHistory";
import { selectionOffsets } from "./editorSelection";

export type EditorSelection = { start: number; end: number; text: string; rect: DOMRect };
export type RubyPopoverState = { start: number; end: number; item?: LinePronunciation; x: number; y: number };

function watchSelection(selection: EditorSelection, editor: RefObject<HTMLDivElement | null>, wrap: RefObject<HTMLDivElement | null>, clear: () => void, setShow: (value: boolean) => void) {
  const move = (event: PointerEvent) => {
    if (event.target instanceof Element && event.target.closest(".ruby-selection-action")) return;
    const { left, right, top, bottom } = selection.rect;
    setShow(event.clientX >= left && event.clientX <= right && event.clientY >= top && event.clientY <= bottom + 10);
  };
  const selectionChanged = () => {
    const selected = editor.current && selectionOffsets(editor.current);
    if (!selected || selected.start !== selection.start || selected.end !== selection.end) clear();
  };
  const focusChanged = (event: FocusEvent) => {
    if (!wrap.current?.contains(event.target as Node)) clear();
  };
  const key = (event: KeyboardEvent) => {
    if (event.key === "Escape") clear();
  };
  document.addEventListener("pointermove", move);
  document.addEventListener("selectionchange", selectionChanged);
  document.addEventListener("focusin", focusChanged);
  document.addEventListener("keydown", key);
  return () => {
    document.removeEventListener("pointermove", move);
    document.removeEventListener("selectionchange", selectionChanged);
    document.removeEventListener("focusin", focusChanged);
    document.removeEventListener("keydown", key);
  };
}

export function useRubyEditing({
  value,
  normalized,
  editor,
  wrap,
  composing,
  changeLocally,
  onCommit,
  onNotice,
}: {
  value: string;
  normalized: LinePronunciation[];
  editor: RefObject<HTMLDivElement | null>;
  wrap: RefObject<HTMLDivElement | null>;
  composing: RefObject<boolean>;
  changeLocally: (next: LineTextSnapshot) => void;
  onCommit: () => void;
  onNotice?: (message: string) => void;
}) {
  const [selection, setSelection] = useState<EditorSelection | null>(null);
  const [showSelectionAction, setShowSelectionAction] = useState(false);
  const [popover, setPopover] = useState<RubyPopoverState | null>(null);
  const [reading, setReading] = useState("");
  const clearSelection = () => {
    setSelection(null);
    setShowSelectionAction(false);
  };
  useEffect(() => {
    if (!popover) return;
    const close = (event: MouseEvent) => {
      if (!(event.target instanceof Element) || !event.target.closest(".ruby-popover")) setPopover(null);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [popover]);
  useEffect(() => (selection ? watchSelection(selection, editor, wrap, clearSelection, setShowSelectionAction) : undefined), [selection, editor, wrap]);
  const rememberSelection = () => {
    const root = editor.current;
    if (!root || composing.current) return;
    const selected = selectionOffsets(root);
    if (!selected || selected.start === selected.end) return;
    setSelection({ ...selected, text: codePoints(value).slice(selected.start, selected.end).join("") });
    setShowSelectionAction(false);
  };
  const showPointerSelection = (next: EditorSelection) => {
    setSelection(next);
    setShowSelectionAction(true);
  };
  const open = (selected: EditorSelection | ReturnType<typeof selectionOffsets>) => {
    if (!selected || selected.start === selected.end) {
      onNotice?.("ルビを付ける本文を選択してください。");
      return;
    }
    const error = selectionConflict(value, selected.start, selected.end, normalized);
    if (error) {
      onNotice?.(error);
      return;
    }
    setSelection({ ...selected, text: codePoints(value).slice(selected.start, selected.end).join("") });
    setReading("");
    setShowSelectionAction(false);
    setPopover({ start: selected.start, end: selected.end, x: selected.rect.left, y: selected.rect.top });
  };
  const openSelection = () => {
    const selected = editor.current && selectionOffsets(editor.current);
    if (!selection || !selected || selected.start !== selection.start || selected.end !== selection.end || codePoints(value).slice(selection.start, selection.end).join("") !== selection.text) {
      clearSelection();
      return;
    }
    open(selection);
  };
  const edit = (item: LinePronunciation, target: HTMLElement) => {
    const rect = target.getBoundingClientRect();
    clearSelection();
    setReading(item.reading);
    setPopover({ start: item.start, end: item.end, item, x: rect.left, y: rect.top });
  };
  const save = () => {
    if (!popover || !reading || reading.includes("\n")) {
      onNotice?.("読みは空欄や改行を含む内容にできません。");
      return;
    }
    const item = { id: popover.item?.id ?? crypto.randomUUID(), start: popover.start, end: popover.end, text: codePoints(value).slice(popover.start, popover.end).join(""), reading };
    changeLocally({ text: value, pronunciations: normalizeLinePronunciations(value, [...normalized.filter((entry) => entry.id !== item.id), item]) });
    setPopover(null);
    onCommit();
  };
  const remove = () => {
    if (popover?.item) changeLocally({ text: value, pronunciations: normalized.filter((item) => item.id !== popover.item?.id) });
    setPopover(null);
    if (popover?.item) onCommit();
  };
  return { selection, showSelectionAction, popover, reading, setReading, setPopover, clearSelection, rememberSelection, showPointerSelection, openSelection, openKeyboardSelection: () => open(editor.current && selectionOffsets(editor.current)), edit, save, remove };
}
