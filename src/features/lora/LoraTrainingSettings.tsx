import type { LoraTrainingModel } from "./LoraTrainingView";
export function LoraTrainingSettings({ model }: { model: LoraTrainingModel }) {
  return (
    <>
      <label className="dialog-form-field">
        LoRA名
        <input value={model.name} onChange={(event) => model.setName(event.target.value)} placeholder="例：落ち着いた話し方" />
      </label>
      <p className="subtle">確認した音声と台詞を使って学習し、完成したLoRAを保存します。声の個性と話し方を対象にし、感情だけの分離を保証しません。</p>
      <details>
        <summary>管理メモを追加（任意）</summary>
        <label className="dialog-form-field">
          管理メモ
          <textarea value={model.memo} onChange={(event) => model.setMemo(event.target.value)} />
        </label>
        <p className="subtle">名前とメモは学習条件に含めません。</p>
      </details>
      <details open={model.advanced} onToggle={(event) => model.setAdvanced(event.currentTarget.open)}>
        <summary>学習の詳細・動作診断</summary>
        <label className="dialog-form-field">
          学習モード
          <select value={model.mode} onChange={(event) => model.changeMode(event.target.value as "check" | "normal")}>
            <option value="normal">通常の学習</option>
            <option value="check">短い動作診断（3ステップ）</option>
          </select>
        </label>
        <p className="subtle">動作診断は学習と保存が動くか確かめるための設定で、完成品質を評価する学習ではありません。実測参考はM4 Max・6秒の合成素材・3ステップで約11秒。通常学習の時間は未計測です。</p>
        <div className="lora-fields">
          <label className="dialog-form-field">
            学習ステップ
            <input inputMode="numeric" value={model.steps} onChange={(event) => model.setSteps(event.target.value)} />
          </label>
          <label className="dialog-form-field">
            学習率
            <input inputMode="decimal" value={model.rate} onChange={(event) => model.setRate(event.target.value)} />
          </label>
          <label className="dialog-form-field">
            バッチサイズ
            <input inputMode="numeric" value={model.batch} onChange={(event) => model.setBatch(event.target.value)} />
          </label>
        </div>
        <label className="dialog-form-field">
          素材長の上限（秒・空欄で自動）
          <input inputMode="decimal" value={model.seconds} onChange={(event) => model.setSeconds(event.target.value)} placeholder="素材の長さに合わせる" />
        </label>
        <p className="subtle">通常は素材の長さに合わせます。音声を黙って切り詰めません。</p>
      </details>
    </>
  );
}
