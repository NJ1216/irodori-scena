import { Children, type ReactNode, useRef } from "react";
import { DropdownIndicator } from "../shared/DropdownIndicator";
import { ModelSelectionOverlay } from "./ModelSelectionOverlay";
import type { ModelSelectionOption } from "./modelSelectionTypes";
import { useModelSelectionPopover } from "./useModelSelectionPopover";

export type { ModelSelectionOption } from "./modelSelectionTypes";

type Props = {
  label: string;
  selectedId: string | null;
  selectedContent: ReactNode;
  options: ModelSelectionOption[];
  additions: ReactNode;
  loading?: boolean;
  error?: string;
  onSelect: (id: string) => Promise<boolean>;
  onDetails?: () => void;
};

export function ModelSelectionPopover({ label, selectedId, selectedContent, options, additions, loading, error, onSelect, onDetails }: Props) {
  const itemCount = Math.max(1, options.length + Children.count(additions));
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popover = useModelSelectionPopover(itemCount, triggerRef);
  return (
    <div className="model-selection-control" onPointerEnter={popover.cancelClose} onPointerLeave={popover.scheduleClose}>
      <button
        ref={triggerRef}
        type="button"
        className="model-selection-trigger model-board-card is-default"
        aria-haspopup="listbox"
        aria-expanded={popover.open}
        aria-controls={popover.popoverId}
        onPointerEnter={popover.triggerPointerEnter}
        onFocus={popover.triggerFocus}
        onClick={popover.triggerClick}
        onKeyDown={popover.triggerKeyDown}
      >
        {selectedContent}
        <span className="model-selection-chevron" aria-hidden="true">
          <DropdownIndicator />
        </span>
      </button>
      {onDetails && (
        <button type="button" className="model-selection-details" aria-label={`${label}の詳細`} onClick={onDetails}>
          詳細
        </button>
      )}
      {popover.open && (
        <ModelSelectionOverlay
          label={label}
          selectedId={selectedId}
          options={options}
          additions={additions}
          loading={loading}
          error={error}
          popoverId={popover.popoverId}
          placement={popover.placement}
          cancelClose={popover.cancelClose}
          scheduleClose={popover.scheduleClose}
          close={popover.close}
          optionKeyDown={popover.optionKeyDown}
          onSelect={onSelect}
        />
      )}
    </div>
  );
}
