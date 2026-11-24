import { LoraMaterialStep, LoraReviewStep, LoraStartStep, LoraResultStep } from "./LoraWizardSteps";
import { LoraManagementBack } from "./LoraManagementBack";
import { TrainingJob } from "./LoraTrainingJob";
import type { LoraTrainingModel } from "./LoraTrainingView";
type Props = { model: LoraTrainingModel; step: number; setStep: (step: number) => void; currentJob?: LoraTrainingModel["jobs"][number]; reviewError: string; confirmInputs: () => void; start: () => Promise<void>; onBack: () => void; onShowJob: (id: string) => void };
export function LoraTrainingFlow({ model, step, setStep, currentJob, reviewError, confirmInputs, start, onBack, onShowJob }: Props) {
  return (
    <>
      {step === 1 && <LoraManagementBack onBack={onBack} />}
      {model.sourceAdapterId && <p className="subtle">選択したLoRAを追加学習し、新しいLoRAとして保存します。元のLoRAとキャストの配合は保持します。</p>}
      <section className={`panel draft-composer lora-composer${step === 2 ? " lora-review-composer" : ""}`}>
        {step === 1 && <LoraMaterialStep model={model} setStep={setStep} />}
        {step === 2 && <LoraReviewStep model={model} setStep={setStep} error={reviewError} onNext={confirmInputs} />}
        {step === 3 && <LoraStartStep model={model} setStep={setStep} onStart={start} />}
        {step === 4 && <LoraResultStep model={model} setStep={setStep} job={currentJob} />}
        {model.error && (
          <p role="alert" className="warning-box">
            {model.error}
          </p>
        )}
      </section>
      {currentJob && step !== 4 && step !== 2 && (
        <section className="panel">
          <TrainingJob model={model} job={currentJob} />
          <button
            type="button"
            className="secondary"
            onClick={() => {
              onShowJob(currentJob.id);
            }}
          >
            学習の進み具合を見る
          </button>
        </section>
      )}
      {currentJob && step === 2 && (
        <button
          type="button"
          className="link-button lora-review-progress"
          onClick={() => {
            onShowJob(currentJob.id);
          }}
        >
          学習の進み具合を見る
        </button>
      )}
    </>
  );
}
