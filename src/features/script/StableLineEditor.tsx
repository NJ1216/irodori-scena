import { memo, useInsertionEffect, useRef, useState } from "react";
import { LineEditor, type LineEditorProps } from "./LineEditor";
import { sameLineEditorProps } from "./stableLineEditorProps";

type Handler = (...args: unknown[]) => unknown;
type Props = Record<string, unknown>;

const MemoLineEditor = memo(LineEditor, sameLineEditorProps as (previous: Readonly<LineEditorProps>, next: Readonly<LineEditorProps>) => boolean);

/**
 * Renders a line card only when its data changed. The scene rebuilds every handler on each render
 * (a selection change, a keystroke or a scroll step), so handlers are passed as stable wrappers that
 * call the newest handler; whether a handler is present still counts as a change, because some
 * controls appear only while several lines are selected.
 */
export function StableLineEditor(props: LineEditorProps) {
  const latest = useRef(props as unknown as Props);
  const [wrappers] = useState(() => new Map<string, Handler>());
  // Updated before any layout effect or event of this commit can call a wrapper.
  useInsertionEffect(() => {
    latest.current = props as unknown as Props;
  });
  const stable: Props = {};
  for (const [key, value] of Object.entries(props)) {
    if (typeof value !== "function") {
      stable[key] = value;
      continue;
    }
    let wrapper = wrappers.get(key);
    if (!wrapper) {
      wrapper = (...args: unknown[]) => (latest.current[key] as Handler | undefined)?.(...args);
      // eslint-disable-next-line react-hooks/refs -- The wrapper reads the ref only when a handler runs, never while rendering.
      wrappers.set(key, wrapper);
    }
    stable[key] = wrapper;
  }
  return <MemoLineEditor {...(stable as unknown as LineEditorProps)} />;
}
