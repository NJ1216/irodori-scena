import { characterMemoLimitError } from "./characterMemo";

export function CharacterMemoField({ value, onChange, label = "自由メモ（任意）", placeholder, className }: { value: string; onChange: (value: string) => void; label?: string; placeholder?: string; className?: string }) {
  const error = characterMemoLimitError(value);
  return (
    <label className={className}>
      {label}
      <textarea aria-label={label} value={value} aria-invalid={Boolean(error)} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} />
      {error && (
        <small className="character-memo-limit-error" role="alert">
          {error}
        </small>
      )}
    </label>
  );
}
