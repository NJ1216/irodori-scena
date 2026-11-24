import { useEffect, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import type { Character } from "../../types";
import { avatarImageUrl } from "../shared/studio-utils";
import { CastPickerMenu } from "./CastPickerMenu";
import { DropdownIndicator } from "../shared/DropdownIndicator";

export function CharacterPicker({ characters, value, disabled, variant = "line", label = "キャストを選択", onChange }: { characters: Character[]; value: string; disabled: boolean; variant?: "line" | "field"; label?: string; onChange: (characterId: string) => void }) {
  const [open, setOpen] = useState(false);
  const [portalStyle, setPortalStyle] = useState<CSSProperties>();
  const root = useRef<HTMLDivElement>(null);
  const selected = characters.find((item) => item.id === value);
  useEffect(() => {
    if (!open) return;
    const closeIfOutside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node) && (!(event.target instanceof Element) || !event.target.closest(".cast-picker-menu"))) setOpen(false);
    };
    document.addEventListener("pointerdown", closeIfOutside);
    return () => document.removeEventListener("pointerdown", closeIfOutside);
  }, [open]);
  useEffect(() => {
    if (!open || variant !== "field") return;
    const update = () => {
      const rect = root.current?.getBoundingClientRect();
      if (!rect) return;
      const backdrop = root.current?.closest<HTMLElement>(".modal-backdrop");
      const backdropLayer = Number.parseInt(backdrop?.style.zIndex ?? "", 10) || 100;
      setPortalStyle({ left: rect.left, top: rect.bottom + 8, width: rect.width, zIndex: backdropLayer + 1 });
    };
    update();
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [open, variant]);
  const choose = (characterId: string) => {
    setOpen(false);
    if (characterId !== value) onChange(characterId);
  };
  return (
    <div ref={root} className={`line-character-picker is-${variant}${open ? " is-open" : ""}`}>
      <button type="button" className="line-character-trigger" disabled={disabled} aria-label={selected ? `${label}：${selected.name}` : label} aria-expanded={open} onClick={() => setOpen((current) => !current)}>
        {selected ? <span className="line-character-avatar">{selected.avatarUrl ? <img src={avatarImageUrl(selected.avatarUrl, selected.avatarVersion)} alt="" /> : selected.name.slice(0, 1)}</span> : <span className="line-character-avatar is-empty">＋</span>}
        {variant === "field" && <span className="line-character-name">{selected?.name ?? "未選択"}</span>}
        <i aria-hidden="true">
          <DropdownIndicator />
        </i>
      </button>
      {open && (variant === "field" && portalStyle ? createPortal(<CastPickerMenu characters={characters} label={label} selectedId={value} portalStyle={portalStyle} onChoose={choose} />, document.body) : <CastPickerMenu characters={characters} label={label} selectedId={value} onChoose={choose} />)}
    </div>
  );
}
