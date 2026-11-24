import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { LoraMix } from "../../types/project";
import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";
import { useLoraRegisterFocus } from "./useLoraRegisterFocus";
import { mixWeights, removeMixEntry, specifyMixWeight, parseMixWeight } from "./loraMix";

type Props = { menu: { index: number; x: number; y: number }; mix: LoraMix; name: string; onChange: (mix: LoraMix) => void; onClose: () => void };
export function MixSegmentActions(props: Props) {
  const { menu, mix, name, onChange, onClose } = props;
  const [editing, setEditing] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ left: menu.x, top: menu.y });
  useLayoutEffect(() => {
    if (editing) return;
    const bounds = ref.current!.getBoundingClientRect();
    setPosition({ left: Math.max(0, Math.min(menu.x, window.innerWidth - bounds.width)), top: Math.max(0, Math.min(menu.y, window.innerHeight - bounds.height)) });
    const trigger = document.activeElement as HTMLElement;
    ref.current?.querySelector<HTMLButtonElement>("button")?.focus();
    return () => {
      if (trigger?.isConnected) trigger.focus();
    };
  }, [menu, editing]);
  useEffect(() => {
    if (editing) return;
    const close = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node)) onClose();
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [editing, onClose]);
  if (editing) return <MixPercentDialog {...props} />;
  return createPortal(
    <div
      ref={ref}
      className="line-context-menu"
      role="menu"
      aria-label={`${name}の操作`}
      style={position}
      onContextMenu={(event) => event.preventDefault()}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          onClose();
        }
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault();
          const buttons = [...ref.current!.querySelectorAll<HTMLButtonElement>("button")];
          const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
          buttons[(index + 1) % buttons.length]?.focus();
        }
      }}
    >
      <button type="button" role="menuitem" onClick={() => setEditing(true)}>
        割合を指定…
      </button>
      {menu.index > 0 && (
        <button
          type="button"
          role="menuitem"
          onClick={() => {
            onChange(removeMixEntry(mix, mix.entries[menu.index - 1].assetId));
            onClose();
          }}
        >
          削除
        </button>
      )}
    </div>,
    document.querySelectorAll(".modal-backdrop").item(document.querySelectorAll(".modal-backdrop").length - 1) ?? document.body,
  );
}
function MixPercentDialog({ menu, mix, name, onChange, onClose }: Props) {
  const [draft, setDraft] = useState(String(mixWeights(mix)[menu.index] / 100));
  const [error, setError] = useState("");
  const ref = useLoraRegisterFocus(false, false);
  return createPortal(
    <ModalBackdrop onClose={onClose}>
      <form
        ref={ref}
        className="modal lora-register-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="mix-percent-title"
        onSubmit={(event) => {
          event.preventDefault();
          event.stopPropagation();
          const result = parseMixWeight(draft, mix.entries.length);
          if (result.weight === undefined) {
            setError(result.error);
            return;
          }
          onChange(specifyMixWeight(mix, menu.index, result.weight));
          onClose();
        }}
      >
        <DialogHeader titleId="mix-percent-title" title="割合を指定" description={name} />
        <label className="dialog-form-field">
          割合（%）
          <input aria-label="割合（%）" inputMode="decimal" value={draft} onChange={(event) => setDraft(event.target.value)} />
        </label>
        {error && (
          <p role="alert" className="warning-text">
            {error}
          </p>
        )}
        <DialogFooter>
          <button type="button" className="secondary" onClick={onClose}>
            キャンセル
          </button>
          <button type="submit" className="primary">
            適用
          </button>
        </DialogFooter>
      </form>
    </ModalBackdrop>,
    document.body,
  );
}
