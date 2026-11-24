/* eslint-disable react-hooks/set-state-in-effect -- This component synchronizes controlled drafts, imperative media, or stable lifecycle owners at explicit boundaries. */
import { InputHTMLAttributes, useEffect, useRef, useState } from "react";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type"> & {
  value: number | undefined;
  onCommit: (value: number | undefined) => void;
  onPrimaryEnter?: (value: number | undefined) => void;
  onArrowStep?: (direction: -1 | 1, current: number | undefined) => number;
  onArrowCommit?: (value: number | undefined, directions: readonly (-1 | 1)[]) => void;
  onArrowPreview?: (directions: readonly (-1 | 1)[] | null) => void;
};

function isPrimaryEnter(event: { key: string; metaKey: boolean; ctrlKey: boolean }) {
  return event.key === "Enter" && (event.metaKey || event.ctrlKey);
}

export function DeferredNumberInput({ value, onCommit, onPrimaryEnter, onArrowStep, onArrowCommit, onArrowPreview, min, max, ...props }: Props) {
  const [draft, setDraft] = useState(value === undefined ? "" : String(value));
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState("");
  const arrowSteps = useRef<Array<-1 | 1>>([]);
  const skipBlurCommit = useRef(false);
  const clearPreview = () => onArrowPreview?.(null);
  useEffect(() => {
    if (!editing && !error) setDraft(value === undefined ? "" : String(value));
  }, [editing, error, value]);
  const commit = (apply = onCommit) => {
    if (!draft.trim()) {
      setError("");
      apply(undefined);
      return;
    }
    const parsed = Number(draft);
    if (!Number.isFinite(parsed) || (min !== undefined && parsed < Number(min)) || (max !== undefined && parsed > Number(max))) {
      setError(`値は${min ?? "制限なし"}〜${max ?? "制限なし"}の範囲で入力してください。`);
      return;
    }
    setError("");
    apply(parsed);
  };
  return (
    <input
      {...props}
      type="number"
      min={min}
      max={max}
      value={draft}
      aria-invalid={Boolean(error)}
      title={error || props.title}
      onFocus={(event) => {
        setEditing(true);
        props.onFocus?.(event);
      }}
      onChange={(event) => {
        clearPreview();
        arrowSteps.current = [];
        skipBlurCommit.current = false;
        setDraft(event.currentTarget.value);
        setError("");
      }}
      onBlur={(event) => {
        setEditing(false);
        if (skipBlurCommit.current) skipBlurCommit.current = false;
        else if (arrowSteps.current.length && onArrowCommit) commit((next) => onArrowCommit(next, arrowSteps.current));
        else commit();
        arrowSteps.current = [];
        clearPreview();
        props.onBlur?.(event);
      }}
      onKeyDown={(event) => {
        if (onPrimaryEnter && isPrimaryEnter(event)) {
          event.preventDefault();
          commit(onPrimaryEnter);
          clearPreview();
          arrowSteps.current = [];
          skipBlurCommit.current = true;
          return;
        }
        if (onArrowStep && (event.key === "ArrowUp" || event.key === "ArrowDown")) {
          event.preventDefault();
          const parsed = Number(draft);
          const direction = event.key === "ArrowUp" ? 1 : -1;
          const next = onArrowStep(direction, draft.trim() && Number.isFinite(parsed) ? parsed : value);
          arrowSteps.current.push(direction);
          onArrowPreview?.([...arrowSteps.current]);
          skipBlurCommit.current = false;
          setDraft(String(next));
          setError("");
          return;
        }
        props.onKeyDown?.(event);
        if (event.defaultPrevented) return;
        if (event.key === "Enter") event.currentTarget.blur();
        if (event.key === "Escape") {
          clearPreview();
          skipBlurCommit.current = true;
          arrowSteps.current = [];
          setDraft(value === undefined ? "" : String(value));
          setError("");
          event.currentTarget.blur();
        }
      }}
    />
  );
}
