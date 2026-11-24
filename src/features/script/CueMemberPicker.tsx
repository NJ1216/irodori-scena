import { useEffect, useRef, useState } from "react";
import type { Character } from "../../types";
import { CastPickerMenu } from "./CastPickerMenu";

const cueMemberMenuTimeoutMs = 4_000;

export function CueMemberPicker({ characters, disabled, onChoose }: { characters: Character[]; disabled: boolean; onChoose: (characterId: string) => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const timeout = window.setTimeout(() => setOpen(false), cueMemberMenuTimeoutMs);
    const closeIfOutside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", closeIfOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      window.clearTimeout(timeout);
      document.removeEventListener("pointerdown", closeIfOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  const choose = (characterId: string) => {
    setOpen(false);
    void onChoose(characterId);
  };

  return (
    <div ref={root} className={`cue-member-add${open ? " is-open" : ""}`}>
      <button type="button" className="cue-member-trigger" title="同時キャストを追加" aria-label="同時キャストを追加" aria-expanded={open} disabled={disabled} onClick={() => setOpen((current) => !current)}>
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="9.5" cy="8" r="3" />
          <path d="M3 21c.3-4.1 3-6.7 6.5-6.7S15.7 16.9 16 21" />
          <path d="M19.5 3.5v5m-2.5-2.5h5" />
        </svg>
      </button>
      {open && <CastPickerMenu characters={characters} label="追加する同時キャスト" align="right" density="compact" onChoose={choose} />}
    </div>
  );
}
