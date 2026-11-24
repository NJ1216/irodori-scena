import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { DialogueLine } from "../../types";
import { LineStatusIcon } from "./LineStatusIcon";

type SeedEditor = { x: number; y: number };

function SeedEditorPopover({ displayedSeed, generating, position, onClose, onGenerate, onNotice }: { displayedSeed: number; generating: boolean; position: SeedEditor; onClose: () => void; onGenerate: (seed: number) => Promise<boolean>; onNotice: (message: string) => void }) {
  const [draft, setDraft] = useState(String(displayedSeed));
  const [submitting, setSubmitting] = useState(false);
  useEffect(() => {
    const close = (event: PointerEvent) => {
      if (!(event.target instanceof Element) || !event.target.closest(".line-seed-editor")) onClose();
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [onClose]);
  const save = async () => {
    if (!/^\d+$/.test(draft)) {
      onNotice("Seedは0〜1999999999の整数で入力してください");
      return;
    }
    const value = Number(draft);
    if (!Number.isSafeInteger(value) || value < 0 || value >= 2_000_000_000) {
      onNotice("Seedは0〜1999999999の整数で入力してください");
      return;
    }
    setSubmitting(true);
    try {
      if (await onGenerate(value)) onClose();
    } finally {
      setSubmitting(false);
    }
  };
  return createPortal(
    <div className="line-seed-editor" style={{ left: position.x, top: position.y }} onPointerDown={(event) => event.stopPropagation()}>
      <input
        aria-label="Seed値"
        inputMode="numeric"
        autoFocus
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            void save();
          }
          if (event.key === "Escape") onClose();
        }}
      />
      <button type="button" className="line-seed-editor-confirm" disabled={generating || submitting} onClick={() => void save()}>
        takeを追加
      </button>
    </div>,
    document.body,
  );
}

export function LineSeedMenu({ line, displayedSeed, generating, onUpdate, onGenerateWithSeed, onNotice }: { line: DialogueLine; displayedSeed: number; generating: boolean; onUpdate: (patch: Partial<DialogueLine>) => void; onGenerateWithSeed: (seed: number) => Promise<boolean>; onNotice: (message: string) => void }) {
  const [open, setOpen] = useState(false);
  const [editor, setEditor] = useState<SeedEditor | null>(null);
  const [menuPosition, setMenuPosition] = useState({ x: 0, y: 0 });
  const root = useRef<HTMLSpanElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const fixed = line.fixedSeed !== undefined || line.manualSeed !== undefined;
  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node) && (!(event.target instanceof Element) || !event.target.closest(".line-seed-menu-items"))) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(String(displayedSeed));
      onNotice(`Seed ${displayedSeed} をコピーしました`);
      setOpen(false);
    } catch {
      onNotice("Seedをコピーできませんでした");
    }
  };
  const openEditor = () => {
    const rect = trigger.current?.getBoundingClientRect();
    if (!rect) return;
    setOpen(false);
    setEditor({ x: rect.left, y: rect.top });
  };
  const openMenu = () => {
    const rect = trigger.current?.getBoundingClientRect();
    if (rect) setMenuPosition({ x: rect.left, y: rect.bottom });
    setOpen(true);
  };
  const leaveMenuArea = (event: React.PointerEvent) => {
    if (event.relatedTarget instanceof Element && event.relatedTarget.closest(".line-seed-menu, .line-seed-menu-items")) return;
    setOpen(false);
  };
  return (
    <>
      <span ref={root} className={`line-seed-menu${open ? " is-open" : ""}`} onPointerEnter={openMenu} onPointerLeave={leaveMenuArea}>
        <button
          ref={trigger}
          type="button"
          className={`line-seed-trigger${fixed ? " is-fixed" : ""}`}
          aria-label={`Seed ${displayedSeed}${fixed ? " 固定中" : ""}`}
          aria-haspopup="menu"
          aria-expanded={open}
          data-preserve-line-selection="true"
          onFocus={openMenu}
          onClick={(event) => {
            event.stopPropagation();
            openMenu();
          }}
        >
          {fixed ? (
            <svg className="line-status-icon line-fixed-seed-icon" viewBox="0 0 24 24" aria-hidden="true">
              <rect x="5" y="5" width="14" height="14" rx="2" />
              <circle cx="12" cy="12" r="2.4" />
            </svg>
          ) : (
            <LineStatusIcon name="seed" />
          )}
          <span className="line-seed-value line-meta-item">{displayedSeed}</span>
        </button>
      </span>
      {open &&
        createPortal(
          <span className="line-seed-menu-items" role="menu" aria-label="Seed操作" style={{ left: menuPosition.x, top: menuPosition.y }} onPointerLeave={leaveMenuArea}>
            <button
              type="button"
              role="menuitem"
              disabled={generating}
              data-preserve-line-selection="true"
              onClick={(event) => {
                event.stopPropagation();
                onUpdate(fixed ? { fixedSeed: undefined, manualSeed: undefined } : { fixedSeed: displayedSeed });
                setOpen(false);
              }}
            >
              {fixed ? "seed値の固定を解除" : "seed値を固定"}
            </button>
            <button
              type="button"
              role="menuitem"
              data-preserve-line-selection="true"
              onClick={(event) => {
                event.stopPropagation();
                void copy();
              }}
            >
              seed値をコピー
            </button>
            <button
              type="button"
              role="menuitem"
              disabled={generating}
              data-preserve-line-selection="true"
              onClick={(event) => {
                event.stopPropagation();
                openEditor();
              }}
            >
              seed値でtakeを追加
            </button>
          </span>,
          document.body,
        )}
      {editor && <SeedEditorPopover displayedSeed={displayedSeed} generating={generating} position={editor} onClose={() => setEditor(null)} onGenerate={onGenerateWithSeed} onNotice={onNotice} />}
    </>
  );
}
