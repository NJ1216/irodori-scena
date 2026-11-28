import { FieldError } from "../shared/InlineValidation";
import { characterMemoLimitError } from "./characterMemo";

export function CharacterMemoField({ value, onChange, label = "自由メモ（任意）", placeholder, className, validationField }: { value: string; onChange: (value: string) => void; label?: string; placeholder?: string; className?: string; validationField?: string }) {
  const error = characterMemoLimitError(value);
  return (
    <label className={className}>
      {label}
      <textarea aria-label={label} data-validation-field={validationField} value={value} aria-invalid={Boolean(error)} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} />
      <FieldError message={error} />
    </label>
  );
}
