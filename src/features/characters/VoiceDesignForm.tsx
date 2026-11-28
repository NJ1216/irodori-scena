import { useEffect, useId, useRef, useState } from "react";
import { FieldError } from "../shared/InlineValidation";
import { createPortal } from "react-dom";
import { InformationTip } from "../shared/InformationTip";
import type { VoiceDesign } from "./voiceDesign";
import { voiceDesignAges, voiceDesignGenders, voiceDesignPitches, voiceDesignQualities, voiceDesignStyles } from "./voiceDesign";

type Field = "age" | "gender" | "pitch" | "qualities" | "style" | "notes";
type Props = { value: VoiceDesign; suggested: Set<Field>; notesError?: string; onChange: (value: VoiceDesign, field: Field) => void };

function Menu({ anchor, children, onClose }: { anchor: HTMLElement; children: React.ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const bounds = anchor.getBoundingClientRect();
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>("button, input")?.focus();
    const outside = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node) && !anchor.contains(event.target as Node)) onClose();
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [anchor, onClose]);
  return createPortal(
    <div
      ref={ref}
      className="voice-design-menu"
      style={{ left: bounds.left, top: Math.min(bounds.bottom + 4, window.innerHeight - 372), width: bounds.width }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          onClose();
          anchor.focus();
          return;
        }
        if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
        event.preventDefault();
        const items = [...(ref.current?.querySelectorAll<HTMLElement>("button, input") ?? [])];
        const index = items.indexOf(document.activeElement as HTMLElement);
        items[(index + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length]?.focus();
      }}
    >
      {children}
    </div>,
    document.body,
  );
}

function SingleSelect({ label, value, options, suggested, onChange }: { label: string; value?: string; options: readonly string[]; suggested: boolean; onChange: (value?: string) => void }) {
  const [open, setOpen] = useState(false);
  const [anchor, setAnchor] = useState<HTMLButtonElement | null>(null);
  const id = useId();
  return (
    <label className={`voice-design-select-field${suggested ? " is-ai-suggested" : ""}`}>
      <span>{label}</span>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={id}
        onClick={(event) => {
          setAnchor(event.currentTarget);
          setOpen((current) => !current);
        }}
        onKeyDown={(event) => {
          if (["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) {
            event.preventDefault();
            setAnchor(event.currentTarget);
            setOpen(true);
          }
          if (event.key === "Escape") setOpen(false);
        }}
      >
        {value || "未選択"}
      </button>
      {open && anchor && (
        <Menu anchor={anchor} onClose={() => setOpen(false)}>
          <div id={id} role="listbox" tabIndex={-1}>
            <button
              type="button"
              role="option"
              aria-selected={!value}
              onClick={() => {
                onChange(undefined);
                setOpen(false);
              }}
            >
              <span>{!value ? "✓" : ""}</span>未選択
            </button>
            {options.map((option) => (
              <button
                type="button"
                role="option"
                aria-selected={value === option}
                key={option}
                onClick={() => {
                  onChange(option);
                  setOpen(false);
                }}
              >
                <span>{value === option ? "✓" : ""}</span>
                {option}
              </button>
            ))}
          </div>
        </Menu>
      )}
    </label>
  );
}

function QualitySelect({ value, suggested, onChange }: { value: string[]; suggested: boolean; onChange: (value: string[]) => void }) {
  const [open, setOpen] = useState(false);
  const [anchor, setAnchor] = useState<HTMLButtonElement | null>(null);
  return (
    <label className={`voice-design-select-field voice-design-quality-field${suggested ? " is-ai-suggested" : ""}`}>
      <span>声質</span>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={(event) => {
          setAnchor(event.currentTarget);
          setOpen((current) => !current);
        }}
        onKeyDown={(event) => {
          if (["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) {
            event.preventDefault();
            setAnchor(event.currentTarget);
            setOpen(true);
          }
          if (event.key === "Escape") setOpen(false);
        }}
      >
        {value.length ? value.join("、") : "未選択"}
      </button>
      {open && anchor && (
        <Menu anchor={anchor} onClose={() => setOpen(false)}>
          <div role="listbox" aria-multiselectable="true" tabIndex={-1}>
            <button type="button" onClick={() => onChange([])}>
              <span>{value.length === 0 ? "✓" : ""}</span>選択を解除
            </button>
            {voiceDesignQualities.map((group) => (
              <section key={group.label}>
                <strong>{group.label}</strong>
                {group.values.map((option) => (
                  <label key={option}>
                    <input type="checkbox" checked={value.includes(option)} onChange={() => onChange(value.includes(option) ? value.filter((item) => item !== option) : [...value, option])} />
                    {option}
                  </label>
                ))}
              </section>
            ))}
          </div>
        </Menu>
      )}
    </label>
  );
}

export function VoiceDesignForm({ value, suggested, notesError = "", onChange }: Props) {
  const set = <K extends keyof VoiceDesign>(key: K, next: VoiceDesign[K], field: Field) => onChange({ ...value, [key]: next }, field);
  return (
    <div className="voice-design-structured-grid">
      <SingleSelect label="年齢" value={value.age} options={voiceDesignAges} suggested={suggested.has("age")} onChange={(next) => set("age", next, "age")} />
      <SingleSelect label="性別" value={value.gender} options={voiceDesignGenders} suggested={suggested.has("gender")} onChange={(next) => set("gender", next, "gender")} />
      <SingleSelect label="声の高さ" value={value.pitch} options={voiceDesignPitches} suggested={suggested.has("pitch")} onChange={(next) => set("pitch", next, "pitch")} />
      <QualitySelect value={value.qualities} suggested={suggested.has("qualities")} onChange={(next) => set("qualities", next, "qualities")} />
      <SingleSelect label="話し方" value={value.style} options={voiceDesignStyles} suggested={suggested.has("style")} onChange={(next) => set("style", next, "style")} />
      <label className={`voice-design-field voice-design-notes-field${suggested.has("notes") ? " is-ai-suggested" : ""}`}>
        <span>追加要望・備考</span>
        <textarea value={value.notes} data-validation-field="notes" aria-invalid={Boolean(notesError) || undefined} onChange={(event) => set("notes", event.target.value, "notes")} placeholder="選択肢にない特徴や補足" />
        <FieldError message={notesError} />
      </label>
    </div>
  );
}

export type VoiceDesignSuggestedField = Field;

export function VoiceDesignTip({ label, paragraphs }: { label: string; paragraphs: string[] }) {
  return <InformationTip ariaLabel={`${label}のヒント`} paragraphs={paragraphs} />;
}
