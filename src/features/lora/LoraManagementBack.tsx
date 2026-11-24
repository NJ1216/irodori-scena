export function LoraManagementBack({ onBack, disabled = false }: { onBack: () => void; disabled?: boolean }) {
  return (
    <div className="lora-step-actions lora-management-back">
      <button type="button" className="secondary" disabled={disabled} onClick={onBack}>
        戻る
      </button>
    </div>
  );
}
