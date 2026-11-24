import { useEffect, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import type { Character } from "../../types";
import { avatarImageUrl } from "../shared/studio-utils";

function CastAvatar({ character }: { character: Character }) {
  const thumbnailUrl = character.avatarThumbnailUrl ?? character.avatarUrl;
  return (
    <span className={`script-assistant-cast-avatar${thumbnailUrl ? " has-image" : ""}`} aria-hidden="true">
      {thumbnailUrl ? <img src={avatarImageUrl(thumbnailUrl, character.avatarVersion)} alt="" /> : character.name.slice(0, 1)}
    </span>
  );
}

export function ScriptAssistantCastPicker({ characters, selectedIds, requiredIds, busy, onChange }: { characters: Character[]; selectedIds: string[]; requiredIds: string[]; busy: boolean; onChange: (ids: string[]) => void }) {
  const [open, setOpen] = useState(false);
  const [menuStyle, setMenuStyle] = useState<CSSProperties>();
  const root = useRef<HTMLDivElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const addButton = useRef<HTMLButtonElement>(null);
  const effectiveIds = Array.from(new Set([...selectedIds, ...requiredIds]));
  const selected = effectiveIds.map((id) => characters.find((item) => item.id === id)).filter(Boolean) as Character[];
  const available = characters.filter((item) => !effectiveIds.includes(item.id));
  useEffect(() => {
    if (!open) return;
    const closeIfOutside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node) && !menu.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", closeIfOutside);
    return () => document.removeEventListener("pointerdown", closeIfOutside);
  }, [open]);
  const menuReady = Boolean(menuStyle);
  useEffect(() => {
    if (open && menuReady) menu.current?.querySelector("button")?.focus();
  }, [open, menuReady]);
  useEffect(() => {
    if (!open) return;
    const update = () => {
      const rect = addButton.current?.getBoundingClientRect();
      if (!rect) return;
      setMenuStyle({ left: rect.left, top: rect.bottom + 8, width: Math.min(360, Math.max(240, root.current?.getBoundingClientRect().width ?? rect.width)) });
    };
    update();
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [open]);
  const remove = (id: string) => {
    if (requiredIds.includes(id) || effectiveIds.length <= 1) return;
    onChange(effectiveIds.filter((item) => item !== id));
  };
  const add = (id: string) => {
    onChange([...effectiveIds, id]);
    setOpen(false);
  };
  return (
    <div className="script-assistant-cast-picker" ref={root}>
      <div className="script-assistant-cast-slots" role="list" aria-label="選択中の生成対象キャスト">
        {selected.map((character) => {
          const required = requiredIds.includes(character.id);
          const last = effectiveIds.length <= 1;
          return (
            <div className="script-assistant-cast-slot" role="listitem" key={character.id}>
              <CastAvatar character={character} />
              <span title={character.name}>{character.name}</span>
              <button type="button" className="script-assistant-cast-remove" aria-label={`${character.name}を生成対象から外す`} title={required ? "言い換え対象の話者は外せません" : last ? "生成対象には1人以上必要です" : "生成対象から外す"} disabled={busy || required || last} onClick={() => remove(character.id)}>
                ×
              </button>
              {required && <small>話者固定</small>}
            </div>
          );
        })}
        <button ref={addButton} type="button" className="script-assistant-cast-add" aria-label="生成対象キャストを追加" aria-expanded={open} disabled={busy || available.length === 0} onClick={() => setOpen((current) => !current)}>
          <span aria-hidden="true">＋</span>
          <small>追加</small>
        </button>
      </div>
      {open &&
        menuStyle &&
        createPortal(
          <div
            ref={menu}
            className="script-assistant-cast-menu is-portal"
            style={menuStyle}
            role="listbox"
            aria-label="追加する生成対象キャスト"
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.stopPropagation();
                setOpen(false);
                addButton.current?.focus();
              }
            }}
          >
            {available.map((character) => (
              <button type="button" role="option" aria-selected="false" key={character.id} onClick={() => add(character.id)}>
                <CastAvatar character={character} />
                <span>{character.name}</span>
              </button>
            ))}
          </div>,
          document.body,
        )}
    </div>
  );
}
