import { StepHeading } from "../shared/StepHeading";
import { LoraInputReview } from "./LoraInputReview";
import { LoraTrainingSettings } from "./LoraTrainingSettings";
import { TrainingJob } from "./LoraTrainingJob";
import type { LoraTrainingModel } from "./LoraTrainingView";
type StepProps = { model: LoraTrainingModel; setStep: (step: number) => void };

export function LoraMaterialStep({ model, setStep }: StepProps) {
  return (
    <>
      <StepHeading number={1}>素材を追加</StepHeading>
      <p className="subtle">WAVと同名の台詞TXTが入ったフォルダを選んでください。サブフォルダも確認し、元ファイルは変更しません。</p>
      <button type="button" className="secondary" disabled={model.busy || model.active} onClick={() => void model.importFolder()}>
        フォルダを選択
      </button>
      {model.folderName && <p className="subtle">{model.folderName}</p>}
      {model.rows.length > 0 && <p className="subtle">{model.rows.length}件を取り込みました。</p>}
      <div className="lora-step-actions">
        <button type="button" className="primary" disabled={!model.rows.length || model.busy || model.active} onClick={() => setStep(2)}>
          内容を確認する
        </button>
      </div>
    </>
  );
}

export function LoraReviewStep({ model, setStep, error: reviewError, onNext: confirmInputs }: StepProps & { error: string; onNext: () => void }) {
  return (
    <>
      <StepHeading number={2}>音声と台詞を確認</StepHeading>
      <LoraInputReview model={model} />
      {reviewError && (
        <p role="alert" className="warning-box">
          {reviewError.split("\n").length}件の不備があります。素材を修正または除外してください。 {reviewError.split("\n")[0]}
        </p>
      )}
      <div className="lora-step-actions lora-review-actions">
        <button type="button" className="secondary" onClick={() => setStep(1)}>
          戻る
        </button>
        <button type="button" className="primary" onClick={confirmInputs}>
          名前と学習へ
        </button>
      </div>
    </>
  );
}

export function LoraStartStep({ model, setStep, onStart: start }: StepProps & { onStart: () => Promise<void> }) {
  return (
    <>
      <StepHeading number={3}>名前をつけて学習</StepHeading>
      <LoraTrainingSettings model={model} />
      {!model.status?.supported && (
        <p role="status" className="warning-box">
          {model.status?.reason ?? "学習環境を確認しています…"}
        </p>
      )}
      <div className="lora-step-actions">
        <button type="button" className="secondary" disabled={model.busy} onClick={() => setStep(2)}>
          戻る
        </button>
        <button type="button" className="primary" disabled={model.busy || model.active || !model.status?.supported} onClick={() => void start()}>
          {model.busy ? "開始しています…" : "学習を開始"}
        </button>
      </div>
    </>
  );
}

export function LoraResultStep({ model, setStep, job: resultJob }: StepProps & { job?: LoraTrainingModel["jobs"][number] }) {
  return (
    <>
      <StepHeading number={4}>結果を保存</StepHeading>
      <TrainingJob model={model} job={resultJob} />
      <div className="lora-step-actions">
        <button type="button" className="secondary" disabled={model.active} onClick={() => setStep(3)}>
          戻る
        </button>
        {!model.active && (
          <button type="button" className="primary" onClick={() => setStep(1)}>
            素材の追加に戻る
          </button>
        )}
      </div>
    </>
  );
}
