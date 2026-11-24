import { type CSSProperties, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type { ModelSelectionOption, Placement } from "./modelSelectionTypes";

type Props = {
  label: string;
  selectedId: string | null;
  options: ModelSelectionOption[];
  additions: ReactNode;
  loading?: boolean;
  error?: string;
  popoverId: string;
  placement: Placement;
  cancelClose: () => void;
  scheduleClose: () => void;
  close: (restoreFocus?: boolean) => void;
  optionKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => void;
  onSelect: (id: string) => Promise<boolean>;
};

function ModelSelectionOptionRow({ option, index, label, selectedId, close, optionKeyDown, onSelect }: { option: ModelSelectionOption; index: number } & Pick<Props, "label" | "selectedId" | "close" | "optionKeyDown" | "onSelect">) {
  return (
    <div className={`model-selection-option-control${option.onDetails ? " has-details" : ""}`} style={{ "--model-option-index": index } as CSSProperties}>
      <button
        type="button"
        role="option"
        aria-selected={option.id === selectedId}
        disabled={option.disabled}
        className={`model-selection-option model-board-card${option.id === selectedId ? " is-default" : ""}`}
        onKeyDown={optionKeyDown}
        onClick={() =>
          void (option.id === selectedId ? Promise.resolve(true) : onSelect(option.id)).then((success) => {
            if (success) close(true);
          })
        }
      >
        {option.content}
      </button>
      {option.onDetails && (
        <button
          type="button"
          className="model-selection-details"
          aria-label={option.detailsLabel ?? `${label}の詳細`}
          onClick={() => {
            close();
            option.onDetails?.();
          }}
        >
          詳細
        </button>
      )}
    </div>
  );
}

export function ModelSelectionOverlay({ label, selectedId, options, additions, loading, error, popoverId, placement, cancelClose, scheduleClose, close, optionKeyDown, onSelect }: Props) {
  return createPortal(
    <div
      id={popoverId}
      className={`model-selection-popover${placement.above ? " is-above" : ""}`}
      role="listbox"
      aria-label={`${label}の候補`}
      style={
        {
          "--model-selection-card-width": `${placement.cardWidth}px`,
          left: placement.left,
          top: placement.top,
          width: placement.width,
          maxHeight: placement.maxHeight,
          transform: placement.above ? "translateY(-100%)" : undefined,
        } as CSSProperties
      }
      onPointerEnter={cancelClose}
      onPointerLeave={scheduleClose}
    >
      <div className="model-selection-grid">
        {options.map((option, index) => (
          <ModelSelectionOptionRow key={option.id} option={option} index={index} label={label} selectedId={selectedId} close={close} optionKeyDown={optionKeyDown} onSelect={onSelect} />
        ))}
        {additions}
      </div>
      {loading && (
        <p className="subtle model-selection-status" role="status">
          読み込んでいます…
        </p>
      )}
      {error && (
        <p className="warning-text model-selection-status" role="alert">
          {error}
        </p>
      )}
    </div>,
    document.body,
  );
}
