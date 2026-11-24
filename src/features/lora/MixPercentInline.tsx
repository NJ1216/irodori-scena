import { useLayoutEffect, useRef, useState } from "react";
import { parseMixWeight } from "./loraMix";

export function MixPercentInline({ weight, count, name, onCommit, onError }: { weight: number; count: number; name: string; onCommit: (weight: number) => void; onError: (error: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const skipBlur = useRef(false);
  useLayoutEffect(() => {
    if (editing) {
      input.current?.focus();
      input.current?.select();
    }
  }, [editing]);
  function begin() {
    setDraft(String(weight / 100));
    setError("");
    onError("");
    skipBlur.current = false;
    setEditing(true);
  }
  function finish(restoreFocus = false) {
    if (skipBlur.current) return;
    const result = parseMixWeight(draft, count);
    input.current?.setCustomValidity(result.error);
    setError(result.error);
    onError(result.error);
    if (result.weight === undefined) return;
    skipBlur.current = true;
    onCommit(result.weight);
    setEditing(false);
    if (restoreFocus) queueMicrotask(() => button.current?.focus());
  }
  if (!editing)
    return (
      <button
        ref={button}
        type="button"
        className="lora-mix-percent"
        aria-label={`${name}の割合 ${weight / 100}%`}
        onDoubleClick={begin}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === "F2") {
            event.preventDefault();
            event.stopPropagation();
            begin();
          }
        }}
      >
        {weight / 100}%
      </button>
    );
  return (
    <input
      ref={input}
      className="lora-mix-percent-input"
      aria-label={`${name}の割合（%）`}
      aria-invalid={Boolean(error)}
      inputMode="decimal"
      value={draft}
      required
      onChange={(event) => {
        setDraft(event.currentTarget.value);
        setError("");
        onError("");
        event.currentTarget.setCustomValidity("");
      }}
      onBlur={() => finish()}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          event.stopPropagation();
          finish(true);
        }
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          skipBlur.current = true;
          setError("");
          onError("");
          setEditing(false);
          queueMicrotask(() => button.current?.focus());
        }
      }}
    />
  );
}
