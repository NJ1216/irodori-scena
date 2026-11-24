import type { ComponentProps, FormEvent } from "react";
import type { HfGgufVariant } from "../../api-llm";
import { formatModelBytes, searchModelTags, type HfModel } from "./huggingFaceModelUi";
import { formatCatalogSize } from "./hfGgufCatalog";
import { HfSearchFilters } from "./HfSearchFilters";

type Props = {
  query: string;
  onQuery: (value: string) => void;
  onSearch: (event: FormEvent) => void;
  busy: boolean;
  hasModels: boolean;
  filters: ComponentProps<typeof HfSearchFilters>;
  models: HfModel[];
  selected: string;
  onSelect: (repoId: string) => void;
  variants: HfGgufVariant[];
  selectedVariant: string;
  onVariant: (id: string) => void;
  message: string;
};

export function HfModelSearch({ query, onQuery, onSearch, busy, hasModels, filters, models, selected, onSelect, variants, selectedVariant, onVariant, message }: Props) {
  return (
    <>
      <form className="hf-search-form" onSubmit={onSearch}>
        <label className="dialog-form-field">
          モデルを検索（1回最大30件）
          <input
            value={query}
            onChange={(event) => onQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && event.nativeEvent.isComposing) event.preventDefault();
            }}
          />
        </label>
        <button type="submit" className="secondary" disabled={busy}>
          検索
        </button>
      </form>
      {(hasModels || !!filters.selected.size || filters.capacity !== null) && <HfSearchFilters {...filters} />}
      <div className="llm-choice-list hf-choice-list" role="radiogroup" aria-label="モデル">
        {models.map((item) => (
          <label key={item.repoId}>
            <input type="radio" name="built-in-model" checked={selected === item.repoId} onChange={() => onSelect(item.repoId)} />
            <span className="hf-choice-main">
              <strong>{item.displayName}</strong>
              <span>
                <small>提供元: {item.publisher}</small>
                {searchModelTags(item).map((tag) => (
                  <small key={`${tag.kind}:${tag.value}`}>{tag.value}</small>
                ))}
              </span>
            </span>
            <b>{formatCatalogSize(item, filters.capacity, filters.selected)}</b>
          </label>
        ))}
      </div>
      {message && (
        <p className="subtle" role="status">
          {message}
        </p>
      )}
      {!!variants.length && (
        <div className="llm-choice-list hf-choice-list" role="radiogroup" aria-label="GGUF量子化">
          {variants.map((variant) => (
            <label key={variant.id}>
              <input type="radio" name="gguf-variant" checked={selectedVariant === variant.id} onChange={() => onVariant(variant.id)} />
              <span className="hf-choice-main">
                <strong>{variant.quantization}</strong>
                <small>{variant.shardCount}ファイル</small>
              </span>
              <b>{formatModelBytes(variant.downloadSizeBytes || null)}</b>
            </label>
          ))}
        </div>
      )}
    </>
  );
}
