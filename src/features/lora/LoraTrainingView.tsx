import { useState } from "react";
import { useLoraTraining } from "./useLoraTraining";
import { inputProblems, runningJob } from "./loraDraft";
import { LoraTrainingFlow } from "./LoraTrainingFlow";
import { LoraLibraryPanel } from "./LoraLibraryPanel";
import { LoraManagementChoices } from "./LoraManagementChoices";
import "../../styles/lora.css";

export type LoraTrainingModel = ReturnType<typeof useLoraTraining>;

export function LoraManagementView() {
  const model = useLoraTraining();
  const [step, setStep] = useState(1);
  const [mode, setMode] = useState<"choose" | "train" | "library">("choose");
  const [jobId, setJobId] = useState("");
  const [reviewError, setReviewError] = useState("");
  const currentJob = jobId ? model.jobs.find((job) => job.id === jobId) : model.jobs.find((job) => runningJob(job.status));
  async function start() {
    const acceptedId = await model.start();
    if (acceptedId) {
      setJobId(acceptedId);
      setStep(4);
    }
  }
  function confirmInputs() {
    const problems = inputProblems(model.rows.filter((row) => !model.excluded.has(row.id)));
    setReviewError(problems.join("\n"));
    if (!problems.length) setStep(3);
  }
  return (
    <section className={`page draft-page lora-training-page${mode === "train" && step === 2 ? " is-review" : ""}`}>
      <div className="page-heading accent-heading">
        <p className="eyebrow type-eyebrow">LORA MANAGEMENT</p>
        <h1 className="type-display">LoRA管理</h1>
        <p className="type-body">LoRAの学習と、登録済みLoRAの管理を行います。</p>
      </div>
      {mode === "choose" && (
        <LoraManagementChoices
          onTrain={() => {
            setJobId("");
            setStep(1);
            model.setSourceAdapterId(undefined);
            setMode("train");
          }}
          onManage={() => setMode("library")}
        />
      )}
      {mode === "library" && (
        <LoraLibraryPanel
          onBack={() => setMode("choose")}
          onContinue={(asset) => {
            setJobId("");
            model.setSourceAdapterId(asset.id);
            model.setName(`${asset.name} 追加学習`);
            model.setMemo(asset.memo ?? "");
            setStep(1);
            setMode("train");
          }}
        />
      )}
      {mode === "train" && (
        <LoraTrainingFlow
          model={model}
          step={step}
          setStep={setStep}
          currentJob={currentJob}
          reviewError={reviewError}
          confirmInputs={confirmInputs}
          start={start}
          onBack={() => setMode("choose")}
          onShowJob={(id) => {
            setJobId(id);
            setStep(4);
          }}
        />
      )}
    </section>
  );
}
