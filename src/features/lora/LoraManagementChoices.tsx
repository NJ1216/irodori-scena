export function LoraManagementChoices({ onTrain, onManage }: { onTrain: () => void; onManage: () => void }) {
  return (
    <div className="cast-action-buttons">
      <button type="button" className="cast-action-button voice" onClick={onTrain}>
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M4 17h6v-6H4zm10 2h6v-6h-6zM10 10h4V6h-4zM6 8l2-2m7 5 2-2M12 2v2m-1-1h2" />
        </svg>
        <b>LoRAを学習する</b>
        <small>TRAIN LORA</small>
      </button>
      <button type="button" className="cast-action-button wav" onClick={onManage}>
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M4 6h16M4 12h16M4 18h16" />
          <circle cx="8" cy="6" r="2" />
          <circle cx="16" cy="12" r="2" />
          <circle cx="10" cy="18" r="2" />
        </svg>
        <b>登録済みLoRAを管理</b>
        <small>MANAGE LORA</small>
      </button>
    </div>
  );
}
