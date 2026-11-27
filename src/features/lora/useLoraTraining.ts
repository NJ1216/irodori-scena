import { useRef, useState } from "react";
import { chooseDirectory } from "../../api";
import { loraApi } from "../../api-lora";
import type { LoraDataset, LoraInputRow, LoraJob, LoraStart, LoraStatus } from "../../types/lora";
import { useLoraJobMonitor } from "./useLoraJobMonitor";
import { inputProblems, parseTrainingLimits, parseTrainingSettings, runningJob } from "./loraDraft";

export function useLoraTraining() {
  const [rows, setRows] = useState<LoraInputRow[]>([]);
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [dataset, setDataset] = useState<LoraDataset | string>("");
  // Keep pre-refresh dataset IDs readable while an existing DEV editor is open.
  const datasetId = typeof dataset === "string" ? dataset : dataset.datasetId;
  const [sourceAdapterId, setSourceAdapterId] = useState<string | undefined>();
  const [name, setName] = useState("");
  const [memo, setMemo] = useState("");
  const [caption, setCaption] = useState("");
  const [speakerId, setSpeakerId] = useState("speaker-1");
  const [mode, setMode] = useState<"check" | "normal">("normal");
  const [advanced, setAdvanced] = useState(false);
  const [steps, setSteps] = useState("1000");
  const [batch, setBatch] = useState("1");
  const [seconds, setSeconds] = useState("");
  const [rate, setRate] = useState("0.0001");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const lock = useRef(false);
  const { status, jobs, setJobs, mutationVersion } = useLoraJobMonitor(setError);
  async function perform(action: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      await action();
      return true;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      return false;
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  const importFiles = (files: File[]) =>
    perform(async () => {
      const dataset = await loraApi.inputs(files);
      setDataset(dataset);
      setRows(dataset.rows);
      setExcluded(new Set());
    });
  async function importFolder() {
    await perform(async () => {
      const path = await chooseDirectory("学習素材のフォルダを選択");
      if (!path) return;
      const next = await loraApi.folderInputs(path);
      setDataset(next);
      setRows(next.rows);
      setExcluded(new Set());
    });
  }
  async function start() {
    let acceptedId: string | null = null;
    const started = await perform(async () => {
      const payload = trainingRequest({ status, jobs, name, rows, excluded, datasetId, memo, mode, steps, rate, batch, seconds });
      const job = await loraApi.start({ ...payload, ...(sourceAdapterId ? { sourceAdapterId } : {}) });
      acceptedId = job.id;
      mutationVersion.current += 1;
      setJobs((current) => [job, ...current.filter((item) => item.id !== job.id)]);
    });
    return started ? acceptedId : null;
  }
  const updateRow = (id: string, values: Partial<LoraInputRow>) => setRows((current) => current.map((row) => (row.id === id ? { ...row, ...values } : row)));
  const toggleExcluded = (id: string) =>
    setExcluded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const cancel = (id: string) =>
    perform(async () => {
      const job = await loraApi.cancel(id);
      mutationVersion.current += 1;
      setJobs((current) => current.map((item) => (item.id === id ? job : item)));
    });
  return {
    sourceAdapterId,
    setSourceAdapterId,
    status,
    jobs,
    rows,
    excluded,
    name,
    setName,
    memo,
    setMemo,
    caption,
    setCaption,
    speakerId,
    setSpeakerId,
    mode,
    changeMode: trainingModeChange(setMode, setSteps, setSeconds),
    advanced,
    setAdvanced,
    steps,
    setSteps,
    batch,
    setBatch,
    seconds,
    setSeconds,
    rate,
    setRate,
    busy,
    error,
    importFiles,
    importFolder,
    folderName: typeof dataset === "string" ? "" : (dataset.folderName ?? ""),
    ignoredTextCount: typeof dataset === "string" ? 0 : (dataset.ignoredTextCount ?? 0),
    start,
    updateRow,
    toggleExcluded,
    cancel,
    bulkCaption: () => setRows((current) => current.map((row) => ({ ...row, caption }))),
    bulkSpeaker: () => setRows((current) => current.map((row) => ({ ...row, speakerId }))),
    active: jobs.some((job) => runningJob(job.status)),
  };
}

type TrainingDraft = { status: LoraStatus | null; jobs: LoraJob[]; name: string; rows: LoraInputRow[]; excluded: Set<string>; datasetId: string; memo: string; mode: "check" | "normal"; steps: string; rate: string; batch: string; seconds: string };
function trainingRequest(draft: TrainingDraft): LoraStart {
  const { status, jobs, name, rows, excluded, datasetId, memo, mode, steps, rate, batch, seconds } = draft;
  if (!status?.supported) throw new Error(status?.reason ?? "学習環境を確認してください。");
  if (jobs.some((job) => runningJob(job.status))) throw new Error("実行中の学習が完了または中断してから開始してください。");
  if (!name.trim()) throw new Error("LoRA名を入力してください。");
  const problems = inputProblems(rows.filter((row) => !excluded.has(row.id)));
  if (problems.length) throw new Error(problems.join("\n"));
  return {
    datasetId,
    name,
    memo,
    mode,
    rows: rows.map(({ id, text, caption: rowCaption, speakerId: rowSpeaker }) => ({ id, text, caption: rowCaption, speakerId: rowSpeaker, excluded: excluded.has(id) })),
    settings: { ...parseTrainingSettings(steps, rate), ...parseTrainingLimits(batch, seconds) },
  };
}

function trainingModeChange(setMode: (value: "check" | "normal") => void, setSteps: (value: string) => void, setSeconds: (value: string) => void) {
  return (value: "check" | "normal") => {
    setMode(value);
    setSteps(value === "check" ? "3" : "1000");
    setSeconds("");
  };
}
