import { MODEL_SIZE_LIMITS, HF_SEARCH_ORDERS, type HfFilterKind, type HfSearchOrder } from "./huggingFaceModelUi";

type Props = {
  tags: Array<{ kind: HfFilterKind; values: string[] }>;
  labels: Record<HfFilterKind, string>;
  selected: Set<string>;
  capacity: number | null;
  disabled: boolean;
  onTag: (tag: { kind: HfFilterKind; value: string }) => void;
  onCapacity: (capacity: number | null) => void;
  onClear: () => void;
  order: HfSearchOrder;
  onOrder: (order: HfSearchOrder) => void;
};

export function HfSearchFilters({ tags, labels, selected, capacity, disabled, onTag, onCapacity, onClear, order, onOrder }: Props) {
  const groups: Array<{ kind: string; label: string; options: Array<{ label: string; active: boolean; toggle: () => void }> }> = tags.map(({ kind, values }) => ({
    kind,
    label: labels[kind],
    options: values.map((value) => ({
      label: value,
      active: selected.has(`${kind}:${value}`),
      toggle: () => onTag({ kind, value }),
    })),
  }));
  groups.splice(1, 0, {
    kind: "capacity",
    label: "容量",
    options: [...MODEL_SIZE_LIMITS, 0].map((value) => ({
      label: value === 0 ? "無制限" : `${value}GB`,
      active: capacity === value,
      toggle: () => onCapacity(capacity === value ? null : value),
    })),
  });
  groups.push({
    kind: "order",
    label: "並び順",
    options: HF_SEARCH_ORDERS.map(({ value, label }) => ({
      label,
      active: order === value,
      toggle: () => onOrder(order === value ? null : value),
    })),
  });
  return (
    <div className="hf-tag-filters" aria-label="モデル検索条件">
      {groups
        .filter((group) => group.options.length)
        .map((group) => (
          <div key={group.kind} role="group" aria-label={group.label}>
            <small>{group.label}</small>
            <span className="hf-tag-values">
              {group.options.map((option) => (
                <button type="button" key={option.label} aria-pressed={option.active} disabled={disabled} onClick={option.toggle}>
                  {option.label}
                </button>
              ))}
            </span>
          </div>
        ))}
      {(selected.size > 0 || capacity !== null || order !== null) && (
        <button type="button" className="hf-clear-tags" disabled={disabled} onClick={onClear}>
          すべて解除
        </button>
      )}
    </div>
  );
}
