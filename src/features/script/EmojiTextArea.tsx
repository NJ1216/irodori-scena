import { primaryModifier } from "../shared/platform";
/* eslint-disable react-hooks/immutability -- This component synchronizes controlled drafts, imperative media, or stable lifecycle owners at explicit boundaries. */
import { Fragment, useMemo, useRef, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { createPortal } from "react-dom";
import type { LinePronunciation } from "../../types";
import { codePoints, normalizeLinePronunciations } from "./linePronunciations";
import { editorText, selectionOffsets } from "./editorSelection";
import { useEmojiHover } from "./useEmojiHover";
import { useLineTextEditing } from "./useLineTextEditing";
import { useRubyEditing, type EditorSelection, type RubyPopoverState } from "./useRubyEditing";

export type LineTextEditorElement = HTMLDivElement;

function revealSelectionAtPointer(root: HTMLElement, value: string, clientX: number, clientY: number, show: (selection: EditorSelection) => void) {
  const selected = selectionOffsets(root);
  if (!selected || selected.start === selected.end) return;
  const { left, right, top, bottom } = selected.rect;
  if (clientX < left || clientX > right || clientY < top || clientY > bottom + 10) return;
  show({ ...selected, text: codePoints(value).slice(selected.start, selected.end).join("") });
}

function selectedEditorText(root: HTMLElement) {
  const selection = window.getSelection();
  if (!selection?.rangeCount || !root.contains(selection.anchorNode) || !root.contains(selection.focusNode)) return null;
  const fragment = selection.getRangeAt(0).cloneContents();
  const container = document.createElement("div");
  container.append(fragment);
  return editorText(container);
}

function commitsLineOnEnter(event: ReactKeyboardEvent<HTMLDivElement>, composing: boolean) {
  return event.key === "Enter" && !event.shiftKey && !event.metaKey && !event.ctrlKey && !event.altKey && !composing && !event.nativeEvent.isComposing && event.nativeEvent.keyCode !== 229;
}

function RubyToken({ item, base, onEdit }: { item: LinePronunciation; base: string; onEdit: (item: LinePronunciation, target: HTMLElement) => void }) {
  const naturalCapacity = Math.max(1, codePoints(base).length * 2);
  const readingLength = Math.max(1, codePoints(item.reading).length);
  const scale = Math.max(2 / 3, Math.min(1, naturalCapacity / readingLength));
  const readingStyle = {
    "--ruby-scale": scale,
    "--ruby-layout-width": `${readingLength * scale}em`,
  } as React.CSSProperties;
  return (
    <ruby
      data-pronunciation-id={item.id}
      onClick={(event) => {
        event.stopPropagation();
        onEdit(item, event.currentTarget);
      }}
    >
      <span className="ruby-base">{base}</span>
      <rt contentEditable={false}>
        <span className="ruby-reading" style={readingStyle}>
          {item.reading}
        </span>
      </rt>
    </ruby>
  );
}

function RubyText({ text, values, onEdit }: { text: string; values: LinePronunciation[]; onEdit: (item: LinePronunciation, target: HTMLElement) => void }) {
  const points = codePoints(text);
  let cursor = 0;
  return (
    <>
      {values.map((item) => {
        const plain = points.slice(cursor, item.start).join("");
        const base = points.slice(item.start, item.end).join("");
        cursor = item.end;
        return (
          <Fragment key={item.id}>
            {plain}
            <RubyToken item={item} base={base} onEdit={onEdit} />
          </Fragment>
        );
      })}
      {points.slice(cursor).join("")}
    </>
  );
}

function RubyPopover({ popover, reading, onReading, onSave, onClose, onDelete }: { popover: RubyPopoverState; reading: string; onReading: (value: string) => void; onSave: () => void; onClose: () => void; onDelete: () => void }) {
  return createPortal(
    <div className="ruby-popover" style={{ left: popover.x, top: popover.y }} onMouseDown={(event) => event.preventDefault()}>
      <input
        aria-label="読み"
        placeholder="読み"
        autoFocus
        value={reading}
        onChange={(event) => onReading(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            onSave();
          }
          if (event.key === "Escape") onClose();
        }}
      />
      {popover.item && (
        <button className="ruby-delete" type="button" aria-label="ルビを削除" onClick={onDelete}>
          <svg className="trash-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4 7h16M10 11v6m4-6v6M9 7l1-2h4l1 2m-9 0 1 13h10l1-13" />
          </svg>
        </button>
      )}
    </div>,
    document.body,
  );
}

export function EmojiTextArea({
  value,
  pronunciations = [],
  onChange,
  onCommit,
  onTextFocus,
  onNotice,
}: {
  value: string;
  pronunciations?: LinePronunciation[];
  onChange: (text: string, pronunciations: LinePronunciation[]) => void;
  onCommit: () => void;
  onTextFocus: (element: LineTextEditorElement) => void;
  onNotice?: (message: string) => void;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const normalized = useMemo(() => normalizeLinePronunciations(value, pronunciations), [pronunciations, value]);
  const { editor, composing, changeLocally, restoreLocalHistory, input, onCompositionStart, onCompositionEnd, onBeforeInput } = useLineTextEditing(value, normalized, onChange);
  const ruby = useRubyEditing({ value, normalized, editor, wrap, composing, changeLocally, onCommit, onNotice });
  const emoji = useEmojiHover();
  const renderKey = value + "\\u0000" + normalized.map((item) => item.id + ":" + item.start + ":" + item.end + ":" + item.reading).join("|");
  return (
    <div ref={wrap} className="line-text-editor-wrap">
      <div
        key={renderKey}
        ref={editor}
        className="line-text-editor"
        contentEditable
        suppressContentEditableWarning
        role="textbox"
        aria-multiline="true"
        data-placeholder="台詞を入力…"
        onFocus={(event) => onTextFocus(event.currentTarget)}
        onMouseUp={ruby.rememberSelection}
        onKeyUp={(event) => {
          if (event.shiftKey) ruby.rememberSelection();
        }}
        onKeyDown={(event) => {
          if (commitsLineOnEnter(event, composing.current)) {
            event.preventDefault();
            event.currentTarget.blur();
            return;
          }
          if (primaryModifier(event) && !event.altKey && event.code === "KeyZ" && !composing.current) {
            event.preventDefault();
            ruby.clearSelection();
            ruby.setPopover(null);
            restoreLocalHistory(event.shiftKey ? "redo" : "undo");
            return;
          }
          if (primaryModifier(event) && !event.altKey && !event.shiftKey && event.code === "KeyR") {
            event.preventDefault();
            ruby.openKeyboardSelection();
          }
        }}
        onMouseMove={(event) => {
          emoji.showEmojiAtPointer(event);
          revealSelectionAtPointer(event.currentTarget, value, event.clientX, event.clientY, ruby.showPointerSelection);
        }}
        onMouseLeave={emoji.hideEmoji}
        onCompositionStart={onCompositionStart}
        onCompositionEnd={onCompositionEnd}
        onInput={input}
        onBeforeInput={(event) => onBeforeInput(event.currentTarget)}
        onBlur={() => {
          if (!ruby.popover) onCommit();
        }}
        onCopy={(event) => {
          const selected = selectedEditorText(event.currentTarget);
          if (selected !== null) {
            event.preventDefault();
            event.clipboardData.setData("text/plain", selected);
          }
        }}
        onPaste={(event) => {
          event.preventDefault();
          document.execCommand("insertText", false, event.clipboardData.getData("text/plain"));
        }}
      >
        <RubyText text={value} values={normalized} onEdit={ruby.edit} />
      </div>
      {ruby.selection &&
        ruby.showSelectionAction &&
        createPortal(
          <div className="ruby-selection-action" style={{ left: ruby.selection.rect.left + ruby.selection.rect.width / 2, top: ruby.selection.rect.bottom + 6 }} onMouseDown={(event) => event.preventDefault()}>
            <button type="button" onClick={ruby.openSelection}>
              読みを設定
            </button>
          </div>,
          document.body,
        )}
      {ruby.popover && <RubyPopover popover={ruby.popover} reading={ruby.reading} onReading={ruby.setReading} onSave={ruby.save} onClose={() => ruby.setPopover(null)} onDelete={ruby.remove} />}
      {emoji.emojiTooltip}
    </div>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function insertIntoLineEditor(element: LineTextEditorElement, text: string) {
  element.focus();
  document.execCommand("insertText", false, text);
}

// eslint-disable-next-line react-refresh/only-export-components
export function insertIntoLineEditorAtRange(element: LineTextEditorElement, text: string, range: Range) {
  element.focus({ preventScroll: true });
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
  document.execCommand("insertText", false, text);
}
