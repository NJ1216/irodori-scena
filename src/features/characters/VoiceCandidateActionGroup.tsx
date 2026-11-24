export function VoiceCandidateActionGroup({
  label,
  disabled = false,
  generating = false,
  clearDisabled = false,
  generateLabel = `${label}の候補をつくる`,
  referenceLabel = `${label}の参照を追加`,
  clearLabel = `${label}の候補を消去`,
  onGenerate,
  onReference,
  onClear,
}: {
  label: string;
  disabled?: boolean;
  generating?: boolean;
  clearDisabled?: boolean;
  generateLabel?: string;
  referenceLabel?: string;
  clearLabel?: string;
  onGenerate?: () => void;
  onReference?: () => void;
  onClear?: () => void;
}) {
  return (
    <span className="voice-candidate-action-group" role="group" aria-label={`${label}の候補操作`}>
      <button type="button" className="is-generate" aria-label={generateLabel} disabled={disabled} onClick={onGenerate}>
        {generating ? "生成中…" : "生成"}
      </button>
      <button type="button" className="is-reference" aria-label={referenceLabel} disabled={disabled} onClick={onReference}>
        参照
      </button>
      <button type="button" className="is-clear" aria-label={clearLabel} disabled={disabled || clearDisabled} onClick={onClear}>
        Clear
      </button>
    </span>
  );
}
