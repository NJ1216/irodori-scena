import { codePoints } from "./linePronunciations";

export function editorText(root: HTMLElement) {
  let result = "";
  const visit = (node: Node) => {
    if (node instanceof HTMLElement && node.tagName === "RT") return;
    if (node instanceof HTMLBRElement) {
      result += "\n";
      return;
    }
    if (node.nodeType === Node.TEXT_NODE) {
      result += node.textContent ?? "";
      return;
    }
    const block = node instanceof HTMLElement && (node.tagName === "DIV" || node.tagName === "P");
    if (block && result && !result.endsWith("\n")) result += "\n";
    node.childNodes.forEach(visit);
    if (block && node.nextSibling && !result.endsWith("\n")) result += "\n";
  };
  root.childNodes.forEach(visit);
  return result.replace(/\r/g, "");
}

function pointOffset(root: HTMLElement, node: Node, offset: number) {
  const range = document.createRange();
  range.setStart(root, 0);
  range.setEnd(node, offset);
  const container = document.createElement("div");
  container.append(range.cloneContents());
  return codePoints(editorText(container)).length;
}

type PointCaretDocument = Document & {
  caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null;
  caretRangeFromPoint?: (x: number, y: number) => Range | null;
};

function rangeOutsideReading(root: HTMLElement, range: Range, x: number) {
  const element = range.startContainer instanceof Element ? range.startContainer : range.startContainer.parentElement;
  const reading = element?.closest("rt");
  if (!reading || !root.contains(reading)) return range;
  const ruby = reading.closest("ruby");
  if (!ruby) return null;
  const corrected = document.createRange();
  if (x < ruby.getBoundingClientRect().left + ruby.getBoundingClientRect().width / 2) corrected.setStartBefore(ruby);
  else corrected.setStartAfter(ruby);
  corrected.collapse(true);
  return corrected;
}

export function editorCaretRangeAtPoint(root: HTMLElement, x: number, y: number) {
  const pointDocument = document as PointCaretDocument;
  let range: Range | null = null;
  const position = pointDocument.caretPositionFromPoint?.(x, y);
  if (position) {
    range = document.createRange();
    range.setStart(position.offsetNode, position.offset);
    range.collapse(true);
  } else {
    range = pointDocument.caretRangeFromPoint?.(x, y) ?? null;
  }
  if (!range || !root.contains(range.startContainer)) return null;
  return rangeOutsideReading(root, range, x);
}

export function caretMarkerRect(root: HTMLElement, range: Range, x: number) {
  const rect = range.getBoundingClientRect();
  if (rect.height > 0) return rect;
  const rootRect = root.getBoundingClientRect();
  return new DOMRect(Math.max(rootRect.left + 6, Math.min(x, rootRect.right - 6)), rootRect.top + 6, 0, Math.max(20, rootRect.height - 12));
}

export function selectionOffsets(root: HTMLElement) {
  const selection = window.getSelection();
  if (!selection?.rangeCount || !root.contains(selection.anchorNode) || !root.contains(selection.focusNode)) return null;
  const range = selection.getRangeAt(0);
  return {
    start: pointOffset(root, range.startContainer, range.startOffset),
    end: pointOffset(root, range.endContainer, range.endOffset),
    rect: range.getBoundingClientRect(),
  };
}

export function editorCaretOffset(root: HTMLElement) {
  const selection = window.getSelection();
  if (!selection?.rangeCount || !root.contains(selection.focusNode)) return null;
  return pointOffset(root, selection.focusNode!, selection.focusOffset);
}
